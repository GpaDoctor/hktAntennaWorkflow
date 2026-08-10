import os
import requests
from pdf_utils import convert_png_to_pdf

# Bot Builder Credentials & Configuration
GROUP_ID = 10301101
X_API_KEY = 'lACjHonswsskX581bLDWUNn1gsl1YaCr'
ENV = 'prd'
PROXY_ENABLED = True
DEFAULT_MODEL = "gpt-5.4"

PROXIES = {
    'http': 'http://proxy.pccw.com:8080',
    'https': 'http://proxy.pccw.com:8080'
}

HEADERS = {
    'x-api-key': X_API_KEY
}

# def upload_chat_file(file_path):
#     """
#     Uploads a floorplan image to the Bot Builder platform and returns the s3Basename file ID.
#     """
#     url = f"https://api.{ENV}.bot-builder.pccw.com/v1/groups/{GROUP_ID}/chat-files?chatApproach=cwf"
    
#     with open(file_path, 'rb') as file:
#         files = {'file': file}
#         try:
#             with requests.post(
#                 url,
#                 files=files,
#                 headers=HEADERS,
#                 proxies=PROXIES if PROXY_ENABLED else None,
#                 verify=True
#             ) as response:
#         #         if response.status_code != 200:
#         #             raise Exception(f"File upload failed ({response.status_code}): {response.text}")
#         #         return response.json()
#         # except Exception as e:
#         #     raise Exception(f"Error during file upload: {e}")
#                 if not response.ok:
#                      raise Exception(f"File upload failed ({response.status_code}): {response.text}")
#                 return response.json()
#         except Exception as e:
#             raise Exception(f"Error during file upload: {e}")

def upload_chat_file(file_path):
    url = f"https://api.{ENV}.bot-builder.pccw.com/v1/groups/{GROUP_ID}/chat-files?chatApproach=cwf"
    
    temp_pdf_path = None
    upload_path = file_path
    ext = os.path.splitext(file_path)[1].lower()

    # If the file is an image, convert to PDF via pdf_utils before uploading
    if ext in ['.png', '.jpg', '.jpeg']:
        temp_pdf_path = convert_png_to_pdf(file_path)
        upload_path = temp_pdf_path

    try:
        with open(upload_path, 'rb') as file:
            files = {'file': file}
            with requests.post(
                url,
                files=files,
                headers=HEADERS,
                proxies=PROXIES if PROXY_ENABLED else None,
                verify=True
            ) as response:
                if not response.ok:
                    raise Exception(f"File upload failed ({response.status_code}): {response.text}")
                return response.json()
    except Exception as e:
        raise Exception(f"Error during file upload: {e}")
    finally:
        # Clean up temporary PDF if generated
        if temp_pdf_path and os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)

def call_bot_builder_chat(data):
    """
    Sends the request payload to the Bot Builder chat endpoint.
    """
    url = f"https://api.{ENV}.bot-builder.pccw.com/v1/groups/{GROUP_ID}/llm-model/chat"
    
    try:
        with requests.post(
            url,
            json=data,
            headers=HEADERS,
            proxies=PROXIES if PROXY_ENABLED else None,
            verify=True
        ) as response:
    #         if response.status_code != 200:
    #             raise Exception(f"Bot Builder Chat API error ({response.status_code}): {response.text}")
    #         return response.json()
    # except Exception as e:
    #     raise Exception(f"Error calling Bot Builder API: {e}")
    # Accept 200 OK or 201 Created as success
# response.ok handles 200, 201, and all other 2xx success status codes
            if not response.ok:
                raise Exception(f"File upload failed ({response.status_code}): {response.text}")
            return response.json()
    except Exception as e:
        raise Exception(f"Error during file upload: {e}")

def analyze_floorplan_with_bot(prompt_text, image_file_path, model=DEFAULT_MODEL):
    """
    Handles the full workflow:
    1. Uploads the image file to Bot Builder.
    2. Sends the prompt and file ID to the Chat-With-File (cwf) endpoint.
    3. Returns the assistant's response string.
    """
    # 1. Upload floorplan image to get s3Basename
    upload_response = upload_chat_file(image_file_path)
    s3_basename = upload_response.get("s3Basename")

    if not s3_basename:
        raise Exception(f"Could not retrieve s3Basename from upload response: {upload_response}")

    # 2. Build payload for multimodal Chat-With-File (cwf) approach
    payload = {
        "approach": "cwf",
        "overrides": {
            "top": 0,
            "model": model,
            "prompt_template": "",
            "max_tokens": 20000,  # <--- Increase from 2000 to 4096
            "temperature": 0,
            "top_p": 0.95,
            "presence_penalty": 0,
            "frequency_penalty": 0
        },
        "files": [
            {
                "data_source": "upload",
                "file_id": s3_basename
            }
        ],
        "history": [
            {
                "role": "user",
                "content": prompt_text
            }
        ]
    }

    # 3. Call Chat API and extract answer string
    result = call_bot_builder_chat(payload)
    return result.get("answer", "")

