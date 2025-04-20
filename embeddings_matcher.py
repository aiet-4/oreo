from loguru import logger
import numpy as np
from sentence_transformers import SentenceTransformer
import json
from typing import List, Dict, Any, Tuple, Optional

class EmbeddingsMatcher:
    def __init__(
        self,
        redis_client,
        model_name: str = "sentence-transformers/all-MiniLM-L12-v2",
        similarity_threshold: float = 0.95,
        use_gpu: bool = False
    ):
        """
        Initialize the EmbeddingsMatcher with a SentenceTransformer model
        
        Args:
            redis_client: Existing Redis client connection
            model_name: The name of the SentenceTransformer model to use
            similarity_threshold: Threshold above which receipts are considered duplicates
            use_gpu: Whether to use GPU for embeddings generation
        """
        # Use the existing Redis client
        self.redis = redis_client
        
        # Initialize the model
        if use_gpu:
            self.model = SentenceTransformer(model_name).cuda()
        else:
            self.model = SentenceTransformer(model_name, device="cpu")
        
        self.similarity_threshold = similarity_threshold
        # Note: mpnet doesn't require prompt_name like stella does
    
    def get_embedding(self, text: str) -> np.ndarray:
        """
        Generate embedding for a piece of text
        
        Args:
            text: The text to embed
            
        Returns:
            Embedding vector as numpy array
        """
        # Directly encode without prompt_name
        return self.model.encode([text])[0]
    
    def save_receipt(
        self, 
        receipt_type: str, 
        file_id: str, 
        image_base64: str, 
        receipt_content: str
    ) -> Dict[str, Any]:
        """
        Save a complete receipt record with content, image, and embeddings
        
        Args:
            receipt_type: Type of the receipt (e.g., "FOOD_EXPENSE")
            file_id: Unique identifier for the receipt file
            image_base64: Base64-encoded image of the receipt
            receipt_content: Text content extracted from the receipt
            
        Returns:
            Dictionary with save status and receipt ID
        """
        try:
            # Generate embedding for the receipt content
            embedding = self.get_embedding(receipt_content)
            
            # Create receipt object with all data
            receipt_data = {
                "file_id": file_id,
                "receipt_type": receipt_type,
                "receipt_content": receipt_content,
                "base_64_image": image_base64,  # Store the base64 image
                "embedding": embedding.tolist(),  # Convert numpy array to list for storage
            }
            
            # Store in Redis
            key = f"receipt:{receipt_type}:{file_id}"
            self.redis.set(key, json.dumps(receipt_data))
            
            return {
                "success": True,
                "message": f"Receipt saved with ID: {file_id}",
                "file_id": file_id
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Error saving receipt: {str(e)}",
                "file_id": file_id
            }    
        
    def get_stored_receipts(self, receipt_type: str) -> List[Dict[str, Any]]:
        """
        Retrieve all stored receipts of a specific type from Redis
        
        Args:
            receipt_type: Type of receipt to retrieve (e.g., "FOOD_EXPENSE")
            
        Returns:
            List of receipt data dictionaries
        """
        pattern = f"receipt:{receipt_type}:*"
        keys = self.redis.keys(pattern)
        receipts = []
        
        for key in keys:
            receipt_data = self.redis.get(key)
            if receipt_data:
                try:
                    # If stored as bytes, decode to string
                    if isinstance(receipt_data, bytes):
                        receipt_data = receipt_data.decode('utf-8')
                    receipt_json = json.loads(receipt_data)
                    receipts.append(receipt_json)
                except json.JSONDecodeError as e:
                    # Log the error and skip invalid JSON
                    print(f"Error decoding receipt data for key {key}: {str(e)}")
                    continue
        
        return receipts
    
    def calculate_similarity(self, embedding1: np.ndarray, embedding2: np.ndarray) -> float:
        """
        Calculate cosine similarity between two embeddings
        
        Args:
            embedding1: First embedding vector
            embedding2: Second embedding vector
            
        Returns:
            Similarity score between 0 and 1
        """
        # Normalize the vectors
        embedding1_norm = embedding1 / np.linalg.norm(embedding1)
        embedding2_norm = embedding2 / np.linalg.norm(embedding2)
        
        # Calculate cosine similarity
        return float(np.dot(embedding1_norm, embedding2_norm))
            
    def is_duplicate_receipt(
        self, 
        receipt_type: str,
        receipt_content: str
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Check if a receipt is a duplicate using vectorized operations for efficiency
        
        Args:
            receipt_type: Type of receipt being checked
            receipt_content: Content of receipt being checked
            
        Returns:
            Tuple of (is_duplicate, match_details)
        """
        
        if not receipt_content or not receipt_type:
            return False, None
        
        # Get embedding for the new receipt
        new_receipt_embedding = self.get_embedding(receipt_content)
        
        # Get all stored receipts of the same type
        stored_receipts = self.get_stored_receipts(receipt_type)
        
        if not stored_receipts:
            logger.warning("No stored receipts found for the given type.")
            return False, None
        
        # Extract embeddings and file IDs from stored receipts
        embeddings = []
        receipt_objects = []
        
        for receipt in stored_receipts:
            if "embedding" in receipt:
                embeddings.append(np.array(receipt["embedding"]))
                receipt_objects.append(receipt)
        
        if not embeddings:
            return False, None
        
        # Convert list of embeddings to a 2D numpy array
        embeddings_array = np.array(embeddings)
        
        # Normalize the embeddings
        embeddings_norm = embeddings_array / np.linalg.norm(embeddings_array, axis=1, keepdims=True)
        new_embedding_norm = new_receipt_embedding / np.linalg.norm(new_receipt_embedding)
        
        # Calculate cosine similarities in a single vectorized operation
        similarities = np.dot(embeddings_norm, new_embedding_norm)
        
        # Find the highest similarity and corresponding receipt
        max_similarity_idx = np.argmax(similarities)
        max_similarity = similarities[max_similarity_idx]

        print(max_similarity)
        
        if max_similarity >= self.similarity_threshold:
            logger.warning("POSSIBLE DUPLICATE RECEIPT DETECTED")
            most_similar_receipt = receipt_objects[max_similarity_idx]
            print(most_similar_receipt.get("file_id", "unknown"))
            print(max_similarity)
            return True, {
                "message": f"A duplicate receipt was found, perform thorough duplicate check. Similar to receipt ID: {most_similar_receipt.get('file_id', 'unknown')}",
                "matching_file_id": most_similar_receipt.get("file_id", "unknown"),
                "matching_receipt_image": most_similar_receipt.get("base_64_image", "")
            }
        
        return False, None