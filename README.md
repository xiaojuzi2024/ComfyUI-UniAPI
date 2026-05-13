# ComfyUI-UniAPI 🚀

> 通用第三方图像生成 API 调用节点 — 让 ComfyUI 工作流轻松接入任意兼容 OpenAI 格式的图像生成服务。

## 📖 简介

**ComfyUI-UniAPI** 是一个轻量级 ComfyUI 自定义节点，充当"通用 API 图像生成网关"。它允许你在 ComfyUI 工作流中直接调用任意兼容 OpenAI Images API 格式的第三方服务（如 t8star.cn、OpenAI 等），无需编写额外代码。

核心亮点：
- ✅ **文生图 (text2img)** — 通过 JSON 请求生成图像
- ✅ **图生图 (img2img)** — 上传 1~4 张参考图生成新图像
- ✅ **异步任务管理** — 自动创建任务 → 轮询等待 → 获取结果，支持断线续查
- ✅ **同步响应兼容** — 也支持直接返回结果的 API
- ✅ **多种输出格式** — 支持 Base64 和 URL 两种图片返回格式
- ✅ **ComfyUI 原生进度条** — 实时显示生成进度

## ✨ 特性

| 特性 | 说明 |
|------|------|
| **通用兼容** | 兼容任何实现 `v1/images/generations` 和 `v1/images/edits` 端点的 API |
| **异步轮询** | API 返回 `task_id` 后自动每 10 秒轮询一次，最多等待 10 分钟 |
| **断线续查** | 提供已有 `task_id` 即可恢复查询任务状态 |
| **多图输出** | 支持一次生成多张图片（`n` 参数，最多 4 张） |
| **图片输入** | 图生图模式下最多可输入 4 张图片 |
| **灵活参数** | 支持 model、quality、size、background、output_format、moderation、seed 等 |
| **丰富输出** | 输出图像张量 + 图片 URL + task_id + 完整 JSON 响应 |

## 🔧 安装

### 方法一：手动安装（推荐）

1. 进入 ComfyUI 的 `custom_nodes` 目录：
   ```
   cd ComfyUI/custom_nodes/
   ```
2. 克隆本仓库：
   ```bash
   git clone https://github.com/your-username/ComfyUI-UniAPI.git
   ```
3. 重启 ComfyUI。

### 方法二：下载压缩包

1. 下载本仓库的 ZIP 压缩包
2. 解压到 `ComfyUI/custom_nodes/ComfyUI-UniAPI/`
3. 重启 ComfyUI

> **无需额外安装依赖** — 所有依赖（torch、Pillow、requests）均已包含在 ComfyUI 基础环境中。

## 🎮 使用指南

### 在 ComfyUI 中找到节点

- **节点名称**：`UniAPI Model Call`
- **分类路径**：`UniAPI` → `UniAPI Model Call`

### 输入参数

#### 必填参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `api_key` | STRING | API 密钥 |
| `base_url` | STRING | API 基础地址（默认：`https://ai.t8star.cn`） |
| `prompt` | STRING | 正向提示词（多行文本） |
| `mode` | ENUM | 模式：`text2img`（文生图）/ `img2img`（图生图） |

#### 可选参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `model` | STRING | `gpt-image-2` | 模型名称 |
| `image1~image4` | IMAGE | — | 参考图片（仅 img2img 模式使用） |
| `quality` | ENUM | `auto` | 质量：`auto` / `high` / `medium` / `low` |
| `size` | ENUM | `auto` | 尺寸：`auto` / `1024x1024` / `1536x1024` / `1024x1536` |
| `background` | ENUM | `auto` | 背景：`auto` / `transparent` / `opaque` |
| `output_format` | ENUM | `png` | 输出格式：`png` / `jpeg` / `webp` |
| `moderation` | ENUM | `auto` | 审核级别：`auto` / `low` |
| `n` | INT | `1` | 生成图片数量（1~4） |
| `response_format` | ENUM | `url` | 响应格式：`url` / `b64_json` |
| `seed` | INT | `0` | 随机种子（0 表示随机） |
| `task_id` | STRING | — | 已有任务 ID，用于恢复查询 |

### 输出端口

| 端口 | 类型 | 说明 |
|------|------|------|
| `image` | IMAGE | 生成的图像张量（可连接预览/保存节点） |
| `image_url` | STRING | 第一张图片的 URL（如返回格式为 URL） |
| `task_id` | STRING | 异步任务 ID（可保存供后续断线续查） |
| `response` | STRING | 完整 API 响应 JSON（包含详细信息） |

## 📋 工作流示例

### 文生图 (text2img)

```
[CLIP Text Encode] ──→ [UniAPI Model Call] ──→ [Save Image]
                          ├─ mode: text2img
                          ├─ api_key: sk-xxx
                          ├─ base_url: https://ai.t8star.cn
                          └─ prompt: "a cat wearing a hat"
```

### 图生图 (img2img)

```
[Load Image] ──────→ [UniAPI Model Call] ──→ [Save Image]
                       ├─ mode: img2img
                       ├─ api_key: sk-xxx
                       ├─ prompt: "turn this into a cyberpunk style"
                       └─ image1: [connected from Load Image]
```

### 异步任务 + 断线续查

```
第一次运行：
  [UniAPI Model Call] → 输出 task_id: "abc123"

断线后重新运行（输入 task_id）：
  [UniAPI Model Call] ──→ 直接查询 task_id "abc123" 的状态
    ├─ task_id: "abc123"
    └─ (跳过 API 提交，直接查询结果)
```

## 🧩 架构

```
用户输入参数 ──→ UniAPIModelCall.generate_image()
                    │
                    ├── 提供 task_id？──→ 直接查询任务状态
                    │
                    ├── mode == "text2img"
                    │     └── POST {base_url}/v1/images/generations?async=true
                    │
                    ├── mode == "img2img"
                    │     └── POST {base_url}/v1/images/edits?async=true
                    │         (multipart/form-data: 图片 + 文本字段)
                    │
                    ├── 响应含 task_id？
                    │     ├── 是 → 轮询 Thread (10s × 60 次)
                    │     └── 否 → 直接解码同步响应
                    │
                    └── 返回 [IMAGE, URL, task_id, JSON]
```

## 🌐 兼容的 API

本节点兼容实现以下端点的任何 API：

| 端点 | 方法 | 用途 |
|------|------|------|
| `{base_url}/v1/images/generations` | POST | 文生图 |
| `{base_url}/v1/images/edits` | POST | 图生图（multipart/form-data） |
| `{base_url}/v1/images/tasks/{task_id}` | GET | 查询异步任务状态 |

API 格式参考：OpenAI [Images API](https://platform.openai.com/docs/api-reference/images) 规范。

## 📄 许可证

[MIT](LICENSE)

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

如果你觉得这个插件有用，欢迎 ⭐ Star 支持！
