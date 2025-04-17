import torch
import json
import os
from pathlib import Path
from docling_core.types.doc import DoclingDocument
from docling_core.types.doc.document import DocTagsDocument
from transformers import AutoProcessor, AutoModelForVision2Seq
from transformers.image_utils import load_image

def process_images_in_folder():
    DEVICE = "mps"
    print(f"Using device: {DEVICE}")

    # Initialize processor and model
    print("Loading model and processor...")
    processor = AutoProcessor.from_pretrained("ds4sd/SmolDocling-256M-preview")
    model = AutoModelForVision2Seq.from_pretrained(
        "ds4sd/SmolDocling-256M-preview",
        torch_dtype=torch.bfloat16,
        _attn_implementation="eager" #if DEVICE == "cuda" else "eager",
    ).to(DEVICE)
    
    # Create output directory if it doesn't exist
    output_dir = Path("Output")
    output_dir.mkdir(exist_ok=True, parents=True)
    
    # Path to receipts folder
    receipts_folder = Path("receipts")
    
    # Check if folder exists
    if not receipts_folder.exists():
        print(f"Folder '{receipts_folder}' does not exist.")
        return
    
    # Dictionary to store results
    results = {}
    
    # Process each jpg file in the folder
    jpg_files = list(receipts_folder.glob("*.jpg"))
    total_files = len(jpg_files)
    
    print(f"Found {total_files} JPG files in {receipts_folder}")
    
    for i, image_path in enumerate(jpg_files):
        filename = image_path.name
        print(f"Processing {i+1}/{total_files}: {filename}")
        
        try:
            # Load image
            image = load_image(str(image_path))
            
            # Create input messages
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image"},
                        {"type": "text", "text": "Convert this page to docling."}
                    ]
                },
            ]
            
            # Prepare inputs
            prompt = processor.apply_chat_template(messages, add_generation_prompt=True)
            inputs = processor(text=prompt, images=[image], return_tensors="pt")
            inputs = inputs.to(DEVICE)
            
            # Generate outputs
            generated_ids = model.generate(**inputs, max_new_tokens=8192)
            prompt_length = inputs.input_ids.shape[1]
            trimmed_generated_ids = generated_ids[:, prompt_length:]
            doctags = processor.batch_decode(
                trimmed_generated_ids,
                skip_special_tokens=False,
            )[0].lstrip()
            
            # Populate document
            doctags_doc = DocTagsDocument.from_doctags_and_image_pairs([doctags], [image])
            doc = DoclingDocument(name=filename)
            doc.load_from_doctags(doctags_doc)
            
            # Export as markdown and save to results dictionary
            markdown_output = doc.export_to_markdown()
            results[filename] = markdown_output
            
            # Optionally save individual HTML files
            # html_output_path = output_dir / f"{filename.replace('.jpg', '.html')}"
            # doc.save_as_html(html_output_path)
            # print(f"Saved HTML to {html_output_path}")
            
        except Exception as e:
            print(f"Error processing {filename}: {str(e)}")
            results[filename] = {"error": str(e)}
    
    # Save all results to a single JSON file
    json_output_path = output_dir / "docling_results.json"
    with open(json_output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"All processing complete. Results saved to {json_output_path}")

if __name__ == "__main__":
    process_images_in_folder()