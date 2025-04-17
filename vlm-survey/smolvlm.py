from transformers import AutoProcessor, AutoModelForImageTextToText
import torch

model_path = "HuggingFaceTB/SmolVLM2-2.2B-Instruct"
processor = AutoProcessor.from_pretrained(model_path)
model = AutoModelForImageTextToText.from_pretrained(
    model_path,
    torch_dtype=torch.bfloat16,
    _attn_implementation="flash_attention_2"
).to("cuda")

messages = [
    {
        "role": "user",
        "content": [
            {"type": "image", "url": "img_1.jpg"},
            {"type": "text", "text": f"""
Please analyze this receipt image and extract the following information in a structured format:
- Merchant/Store name
- Date of Purchase
- Time of Purchase
- Receipt/transaction number
- Payment method (cash, credit card, etc.)
- CGST
- SGST
- Sub Total
- Total amount

NOTE:
1. DO NOT FABRICATE any data if not available or unclear
2. Only answer the above information, NOTHING extra
            """},
        ]
    },
]

inputs = processor.apply_chat_template(
    messages,
    add_generation_prompt=True,
    tokenize=True,
    return_dict=True,
    return_tensors="pt",
).to(model.device, dtype=torch.bfloat16)

print("generating...")
generated_ids = model.generate(**inputs, do_sample=False, max_new_tokens=512)
generated_texts = processor.batch_decode(
    generated_ids,
    skip_special_tokens=True,
)
print(generated_texts[0])
