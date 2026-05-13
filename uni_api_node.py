import os
import io
import json
import time
import base64
import uuid
import traceback

import torch
import requests
from PIL import Image
from io import BytesIO

import comfy.utils


# ──────────────────────────────────────────────
#  Utility: tensor <-> PIL conversion
# ──────────────────────────────────────────────

def pil2tensor(image):
    """Convert a PIL Image (or list) to a ComfyUI IMAGE tensor."""
    if isinstance(image, list):
        tensors = []
        for img in image:
            img = img.convert("RGB")
            tensors.append(pil2tensor(img))
        return torch.cat(tensors, dim=0)

    img = image.convert("RGB")
    arr = torch.unsqueeze(torch.tensor(
        bytearray(img.tobytes()), dtype=torch.uint8), 0)
    arr = arr.view((img.size[1], img.size[0], 3))
    arr = arr / 255.0
    return arr.unsqueeze(0)


def tensor2pil(image_tensor):
    """Convert a ComfyUI IMAGE tensor to a list of PIL Images."""
    images = []
    batch_count = image_tensor.size(0) if len(image_tensor.shape) > 3 else 1
    for i in range(batch_count):
        if len(image_tensor.shape) > 3:
            img_data = image_tensor[i]  # (H, W, C)
        else:
            img_data = image_tensor
        i_np = img_data.cpu().numpy() * 255.0
        i_np = i_np.clip(0, 255).astype("uint8")
        images.append(Image.fromarray(i_np))
    return images


# ──────────────────────────────────────────────
#  Main Node
# ──────────────────────────────────────────────

class UniAPIModelCall:
    """
    Universal API Model Call node.
    Submits text-to-image / image-to-image requests to a third-party API
    and polls for async results.  Supports b64_json and URL responses.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api_key": ("STRING", {"default": ""}),
                "base_url": ("STRING", {"default": "https://ai.t8star.cn"}),
                "prompt": ("STRING", {"multiline": True}),
                "mode": (["text2img", "img2img"], {"default": "text2img"}),
            },
            "optional": {
                "model": ("STRING", {"default": "gpt-image-2"}),
                "image1": ("IMAGE",),
                "image2": ("IMAGE",),
                "image3": ("IMAGE",),
                "image4": ("IMAGE",),
                "quality": (["auto", "high", "medium", "low"], {"default": "auto"}),
                "size": (["auto", "1024x1024", "1536x1024", "1024x1536"], {"default": "auto"}),
                "background": (["auto", "transparent", "opaque"], {"default": "auto"}),
                "output_format": (["png", "jpeg", "webp"], {"default": "png"}),
                "moderation": (["auto", "low"], {"default": "auto"}),
                "n": ("INT", {"default": 1, "min": 1, "max": 4}),
                "task_id": ("STRING", {"default": ""}),
                "response_format": (["url", "b64_json"], {"default": "url"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 2147483647}),
            }
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("image", "image_url", "task_id", "response")
    FUNCTION = "generate_image"
    CATEGORY = "UniAPI"

    def __init__(self):
        self.api_key = ""
        self.timeout = 900

    # ── helpers ────────────────────────────────

    def get_headers(self):
        return {"Authorization": f"Bearer {self.api_key}"}

    def image_to_base64(self, image_tensor):
        if image_tensor is None:
            return None
        pil_image = tensor2pil(image_tensor)[0]
        buffered = BytesIO()
        pil_image.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    # ── main entry ─────────────────────────────

    def generate_image(self, api_key, base_url, prompt, mode="text2img",
                       model="gpt-image-2", quality="auto", size="auto",
                       background="auto", output_format="png", moderation="auto",
                       n=1, task_id="", response_format="url", seed=0,
                       image1=None, image2=None, image3=None, image4=None):

        if not api_key.strip():
            error_message = "API key is required"
            print(f"[UniAPI] {error_message}")
            blank = Image.new("RGB", (1024, 1024), color="white")
            return (pil2tensor(blank), "", "",
                    json.dumps({"status": "failed", "message": error_message}))

        self.api_key = api_key

        if not base_url.strip():
            error_message = "base_url is required"
            print(f"[UniAPI] {error_message}")
            blank = Image.new("RGB", (1024, 1024), color="white")
            return (pil2tensor(blank), "", "",
                    json.dumps({"status": "failed", "message": error_message}))

        api_base = base_url.rstrip("/")

        try:
            pbar = comfy.utils.ProgressBar(100)
            pbar.update_absolute(10)

            # If task_id is provided, query existing task
            if task_id.strip():
                print(f"[UniAPI] Querying task status for task_id: {task_id}")
                return self._query_task_status(task_id, pbar, api_base)

            # ── text2img ──
            if mode == "text2img":
                headers = self.get_headers()
                headers["Content-Type"] = "application/json"

                payload = {
                    "prompt": prompt,
                    "model": model,
                    "quality": quality,
                    "size": size,
                    "background": background,
                    "output_format": output_format,
                    "moderation": moderation,
                    "n": n,
                }
                if response_format:
                    payload["response_format"] = response_format
                if seed > 0:
                    payload["seed"] = seed

                params = {"async": "true"}

                print(f"[UniAPI] text2img → {api_base}/v1/images/generations")
                response = requests.post(
                    f"{api_base}/v1/images/generations",
                    headers=headers,
                    params=params,
                    json=payload,
                    timeout=self.timeout,
                )

            # ── img2img ──
            else:
                headers = self.get_headers()
                all_images = [image1, image2, image3, image4]
                files = []
                image_count = 0
                for img in all_images:
                    if img is not None:
                        pil_img = tensor2pil(img)[0]
                        buffered = BytesIO()
                        pil_img.save(buffered, format="PNG")
                        buffered.seek(0)
                        files.append(("image", (f"image_{image_count}.png", buffered, "image/png")))
                        image_count += 1

                data = {
                    "prompt": prompt,
                    "model": model,
                    "quality": quality,
                    "size": size,
                    "background": background,
                    "output_format": output_format,
                    "moderation": moderation,
                    "n": str(n),
                }
                if response_format:
                    data["response_format"] = response_format
                if seed > 0:
                    data["seed"] = str(seed)

                params = {"async": "true"}

                print(f"[UniAPI] img2img → {api_base}/v1/images/edits ({image_count} image(s))")
                response = requests.post(
                    f"{api_base}/v1/images/edits",
                    headers=headers,
                    params=params,
                    data=data,
                    files=files,
                    timeout=self.timeout,
                )

            pbar.update_absolute(30)

            # ── handle response ──
            if response.status_code != 200:
                error_message = f"API Error: {response.status_code} - {response.text}"
                print(f"[UniAPI] {error_message}")
                blank = Image.new("RGB", (1024, 1024), color="white")
                return (pil2tensor(blank), "", "",
                        json.dumps({"status": "failed", "message": error_message}))

            result = response.json()
            print(f"[UniAPI] API response received")

            # ── async (task_id returned) ──
            if "task_id" in result:
                returned_task_id = result["task_id"]
                result_info = {
                    "status": "pending",
                    "task_id": returned_task_id,
                    "model": model,
                    "mode": mode,
                    "prompt": prompt,
                    "quality": quality,
                    "size": size,
                    "seed": seed if seed > 0 else None,
                    "message": "Async task created. Polling for result...",
                }
                print(f"[UniAPI] Async task created: {returned_task_id}")
                pbar.update_absolute(40)

                # Polling loop
                max_attempts = 60
                for attempt in range(1, max_attempts + 1):
                    time.sleep(10)
                    try:
                        query_url = f"{api_base}/v1/images/tasks/{returned_task_id}"
                        query_headers = self.get_headers()
                        query_headers["Content-Type"] = "application/json"
                        qr = requests.get(query_url, headers=query_headers, timeout=self.timeout)

                        if qr.status_code == 200:
                            qr_json = qr.json()
                            actual_status = "unknown"
                            actual_data = None
                            if "data" in qr_json and isinstance(qr_json["data"], dict):
                                actual_status = qr_json["data"].get("status", "unknown")
                                actual_data = qr_json["data"].get("data")

                            print(f"[UniAPI] Task status (attempt {attempt}): {actual_status}")
                            pbar.update_absolute(min(90, 40 + attempt * 50 // max_attempts))

                            if actual_status in ("completed", "success", "done", "finished", "SUCCESS") or \
                               (actual_status == "unknown" and actual_data):
                                if actual_data:
                                    return self._process_image_data(
                                        actual_data, returned_task_id, model, mode,
                                        prompt, quality, size, seed, pbar)

                            elif actual_status in ("failed", "error", "FAILURE"):
                                err_msg = qr_json.get("error", "Unknown error")
                                print(f"[UniAPI] Task failed: {err_msg}")
                                blank = Image.new("RGB", (1024, 1024), color="red")
                                pbar.update_absolute(100)
                                return (pil2tensor(blank), "", returned_task_id,
                                        json.dumps({"status": "failed", "task_id": returned_task_id, "message": err_msg}))
                    except Exception as e:
                        print(f"[UniAPI] Error polling task: {e}")

                # Timeout
                print(f"[UniAPI] Task polling timed out")
                blank = Image.new("RGB", (512, 512), color="yellow")
                pbar.update_absolute(100)
                return (pil2tensor(blank), "", returned_task_id,
                        json.dumps({"status": "timeout", "task_id": returned_task_id,
                                    "message": "Task polling timed out. Query manually using task_id."}))

            # ── sync (data returned directly) ──
            elif "data" in result and result["data"]:
                print(f"[UniAPI] Sync response – {len(result['data'])} image(s)")
                return self._process_sync_data(result, model, mode, prompt, quality, size, seed, pbar)

            else:
                error_message = f"Unexpected API response: {result}"
                print(f"[UniAPI] {error_message}")
                blank = Image.new("RGB", (1024, 1024), color="white")
                return (pil2tensor(blank), "", "",
                        json.dumps({"status": "failed", "message": error_message}))

        except Exception as e:
            error_message = f"Error: {e}"
            print(f"[UniAPI] {error_message}")
            traceback.print_exc()
            blank = Image.new("RGB", (1024, 1024), color="white")
            return (pil2tensor(blank), "", "",
                    json.dumps({"status": "failed", "message": error_message}))

    # ── process async image data ───────────────

    def _process_image_data(self, actual_data, task_id, model, mode, prompt,
                            quality, size, seed, pbar):
        generated_tensors = []
        image_urls = []

        data_items = actual_data.get("data", []) if isinstance(actual_data, dict) else actual_data
        if not isinstance(data_items, list):
            data_items = [data_items]

        for item in data_items:
            try:
                if "b64_json" in item and item["b64_json"]:
                    img_bytes = base64.b64decode(item["b64_json"])
                    stream = BytesIO(img_bytes)
                    pil_img = Image.open(stream)
                    pil_img.verify()
                    stream.seek(0)
                    pil_img = Image.open(stream).convert("RGB")
                    generated_tensors.append(pil2tensor(pil_img))

                elif "url" in item and item["url"]:
                    image_urls.append(item["url"])
                    resp = requests.get(item["url"], timeout=self.timeout)
                    resp.raise_for_status()
                    stream = BytesIO(resp.content)
                    pil_img = Image.open(stream)
                    pil_img.verify()
                    stream.seek(0)
                    pil_img = Image.open(stream).convert("RGB")
                    generated_tensors.append(pil2tensor(pil_img))
            except Exception as e:
                print(f"[UniAPI] Error processing image: {e}")
                continue

        if generated_tensors:
            combined = torch.cat(generated_tensors, dim=0)
            first_url = image_urls[0] if image_urls else ""
            info = {
                "status": "success",
                "task_id": task_id, "model": model, "mode": mode,
                "prompt": prompt, "quality": quality, "size": size,
                "seed": seed if seed > 0 else None,
                "images_count": len(generated_tensors),
                "image_url": first_url, "all_urls": image_urls,
            }
            pbar.update_absolute(100)
            return (combined, first_url, task_id, json.dumps(info))

        error_message = "No valid images in completed task"
        print(f"[UniAPI] {error_message}")
        blank = Image.new("RGB", (1024, 1024), color="white")
        pbar.update_absolute(100)
        return (pil2tensor(blank), "", task_id,
                json.dumps({"status": "failed", "task_id": task_id, "message": error_message}))

    # ── process sync image data ────────────────

    def _process_sync_data(self, result, model, mode, prompt, quality, size, seed, pbar):
        generated_tensors = []
        image_urls = []

        data_items = result.get("data", [])
        if not isinstance(data_items, list):
            data_items = [data_items]

        for i, item in enumerate(data_items):
            try:
                pbar.update_absolute(50 + (i + 1) * 40 // len(data_items))
                if "b64_json" in item and item["b64_json"]:
                    img_bytes = base64.b64decode(item["b64_json"])
                    stream = BytesIO(img_bytes)
                    pil_img = Image.open(stream)
                    pil_img.verify()
                    stream.seek(0)
                    pil_img = Image.open(stream).convert("RGB")
                    generated_tensors.append(pil2tensor(pil_img))
                elif "url" in item and item["url"]:
                    image_urls.append(item["url"])
                    resp = requests.get(item["url"], timeout=self.timeout)
                    resp.raise_for_status()
                    stream = BytesIO(resp.content)
                    pil_img = Image.open(stream)
                    pil_img.verify()
                    stream.seek(0)
                    pil_img = Image.open(stream).convert("RGB")
                    generated_tensors.append(pil2tensor(pil_img))
            except Exception as e:
                print(f"[UniAPI] Error processing item {i}: {e}")
                continue

        pbar.update_absolute(100)

        if generated_tensors:
            combined = torch.cat(generated_tensors, dim=0)
            first_url = image_urls[0] if image_urls else ""
            sync_id = f"sync_{uuid.uuid4().hex[:16]}"
            info = {
                "status": "success",
                "task_id": sync_id, "model": model, "mode": mode,
                "prompt": prompt, "quality": quality, "size": size,
                "seed": seed if seed > 0 else None,
                "images_count": len(generated_tensors),
                "image_url": first_url, "all_urls": image_urls,
            }
            return (combined, first_url, sync_id, json.dumps(info))

        error_message = "Failed to process any images"
        print(f"[UniAPI] {error_message}")
        blank = Image.new("RGB", (1024, 1024), color="white")
        return (pil2tensor(blank), "", "",
                json.dumps({"status": "failed", "message": error_message}))

    # ── query existing task ────────────────────

    def _query_task_status(self, task_id, pbar, api_base):
        try:
            headers = self.get_headers()
            headers["Content-Type"] = "application/json"

            query_url = f"{api_base}/v1/images/tasks/{task_id}"
            print(f"[UniAPI] Querying task: {query_url}")
            response = requests.get(query_url, headers=headers, timeout=self.timeout)
            pbar.update_absolute(50)

            if response.status_code != 200:
                err = f"Query Error: {response.status_code} - {response.text}"
                print(f"[UniAPI] {err}")
                blank = Image.new("RGB", (1024, 1024), color="white")
                return (pil2tensor(blank), "", task_id,
                        json.dumps({"status": "query_failed", "task_id": task_id, "message": err}))

            result = response.json()
            actual_status = "unknown"
            actual_data = None
            if "data" in result and isinstance(result["data"], dict):
                actual_status = result["data"].get("status", "unknown")
                actual_data = result["data"].get("data")

            if actual_status in ("completed", "success", "done", "finished", "SUCCESS") or \
               (actual_status == "unknown" and actual_data):
                if actual_data:
                    generated_tensors = []
                    image_urls = []
                    data_items = result.get("data", [])
                    if not isinstance(data_items, list):
                        data_items = [data_items]
                    for item in data_items:
                        try:
                            if "b64_json" in item and item["b64_json"]:
                                img_bytes = base64.b64decode(item["b64_json"])
                                stream = BytesIO(img_bytes)
                                pil_img = Image.open(stream).convert("RGB")
                                generated_tensors.append(pil2tensor(pil_img))
                            elif "url" in item and item["url"]:
                                image_urls.append(item["url"])
                                resp = requests.get(item["url"], timeout=self.timeout)
                                resp.raise_for_status()
                                pil_img = Image.open(BytesIO(resp.content)).convert("RGB")
                                generated_tensors.append(pil2tensor(pil_img))
                        except Exception:
                            continue

                    if generated_tensors:
                        combined = torch.cat(generated_tensors, dim=0)
                        first_url = image_urls[0] if image_urls else ""
                        pbar.update_absolute(100)
                        return (combined, first_url, task_id,
                                json.dumps({"status": "success", "task_id": task_id, "images_count": len(generated_tensors)}))
            elif actual_status in ("failed", "error", "FAILURE"):
                blank = Image.new("RGB", (1024, 1024), color="red")
                pbar.update_absolute(100)
                return (pil2tensor(blank), "", task_id,
                        json.dumps({"status": "failed", "task_id": task_id, "message": "Task failed"}))

            blank = Image.new("RGB", (1024, 1024), color="white")
            pbar.update_absolute(100)
            return (pil2tensor(blank), "", task_id,
                    json.dumps({"status": "incomplete", "task_id": task_id, "message": f"Status: {actual_status}"}))
        except Exception as e:
            print(f"[UniAPI] Error querying task: {e}")
            traceback.print_exc()
            blank = Image.new("RGB", (1024, 1024), color="white")
            return (pil2tensor(blank), "", task_id,
                    json.dumps({"status": "error", "task_id": task_id, "message": str(e)}))


# ── registration ────────────────────────────────

NODE_CLASS_MAPPINGS = {
    "UniAPIModelCall": UniAPIModelCall,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "UniAPIModelCall": "UniAPI Model Call",
}
