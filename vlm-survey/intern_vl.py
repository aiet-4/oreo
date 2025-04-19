from openai import OpenAI
import base64

client = OpenAI(api_key="123-456", base_url="https://2e6e-182-74-119-254.ngrok-free.app/v1")

model = "OpenGVLab/InternVL3-2B"

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

def ocr_page_with_rolm(img_base64):
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_base64}"},
                    },
                    {
                        "type": "text",
                        "text": f"""
Please analyze this receipt image and extract the following information in a structured format:
- Merchant/Store name
- Date of Purchase
- Time of Purchase
- Receipt/transaction number
- Payment method (cash, credit card, etc.)
- CGST (Amount)
- SGST (Amount)
- Sub Total
- Total amount

NOTE:
1. DO NOT FABRICATE any data if not available or unclear
2. Only answer the above information, NOTHING extra
""",
                    },
                ],
            }
        ],
        temperature=0.1,
        seed=1024,
        max_tokens=512
    )
    return response.choices[0].message.content

test_img_path = "img_2.jpg"
img_base64 = encode_image(test_img_path)
print(ocr_page_with_rolm(img_base64))
