# AI医疗助手

基于React + FastAPI + LangChain + 通义千问的智能医疗问答系统，支持基于检索增强生成(RAG)的医疗知识问答。


正常提问

![AI医疗助手](/frontend/public/nomal.png)

经过RAG处理提问

![AI医疗助手](/frontend/public/ragResult.png)


## 项目简介

AI医疗助手是一个结合了最新人工智能技术的医疗问答系统，旨在为用户提供准确、专业的医疗咨询服务。系统采用前后端分离架构，前端使用React构建友好的用户界面，后端使用FastAPI提供高性能的API服务，并结合LangChain框架和通义千问大语言模型提供智能问答能力。本项目是本人用于学习LangChain框架的练手项目，后续会继续完善。

### 核心功能

- 🩺 **医疗问答**：针对用户的医疗问题提供专业解答
- 💬 **实时对话**：流式响应，打字机效果，提升用户体验
- 🧠 **上下文记忆**：支持多轮对话，理解上下文信息
- 📚 **知识检索**：基于RAG技术，从医疗知识库中检索相关信息
- 🎨 **美观界面**：现代化的聊天UI，支持Markdown渲染
- 🔄 **对话记忆**：自动保存对话历史，支持会话恢复

## 技术栈

### 前端
- **框架**：React 19 + TypeScript
- **状态管理**：React Hooks
- **样式**：CSS Modules
- **网络请求**：Fetch API（支持流式响应）
- **组件**：
  - 自定义聊天界面
  - Markdown渲染 (react-markdown)
  - 弹窗组件
  - 消息提示 (react-hot-toast)

### 后端
- **框架**：FastAPI (Python)
- **AI框架**：LangChain 0.3.0
- **大语言模型**：通义千问 (qwen-turbo/qwen-plus/qwen-max)
- **向量数据库**：Chroma
- **文本嵌入**：DashScope Embeddings
- **流式响应**：SSE (Server-Sent Events)
- **文档处理**：LangChain Text Splitters

## 系统架构

```
┌─────────────┐    HTTP/SSE    ┌──────────────┐     API     ┌─────────────┐
│   Frontend  │◄──────────────►│    Backend   │◄───────────►│ Tongyi API  │
│  (React.js) │                │   (FastAPI)  │             │ (qwen-turbo) │
└─────────────┘                └──────────────┘             └─────────────┘
                                      │
                                      │ Query
                                      ▼
                              ┌──────────────┐
                              │Vector Database│
                              │   (Chroma)   │
                              └──────────────┘
                                      │
                                      │ Index
                                      ▼
                              ┌──────────────┐
                              │ Knowledge Base│
                              │  (Markdown)  │
                              └──────────────┘
```

## 安装指南

### 环境要求

- Python 3.10+ (后端)
- Node.js 16+ (前端)
- 通义千问API密钥 (可在[阿里云DashScope](https://dashscope.console.aliyun.com/)申请)

### 后端设置

1. 克隆仓库并进入后端目录
```bash
git clone https://github.com/yourusername/medical-ai-assistant.git
cd medical-ai-assistant/backend
```

2. 创建并激活Python虚拟环境
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

3. 安装依赖
```bash
pip install -r requirements.txt
```

4. 配置环境变量
创建或编辑 `.env` 文件，填入你的通义千问API密钥
```
DASHSCOPE_API_KEY=your_dashscope_api_key_here
PORT=8000
HOST=0.0.0.0
CORS_ALLOW_ORIGINS=http://localhost:3000
```

5. 启动服务器
```bash
python main.py
# 或者使用uvicorn
# uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 前端设置

1. 进入前端目录
```bash
cd ../frontend
```

2. 安装依赖
```bash
npm install
```

3. 启动开发服务器
```bash
npm start
```

4. 浏览器访问 http://localhost:3000 开始使用

## 使用指南

1. **开始对话**：在输入框中输入医疗相关问题，如"高血压应该注意什么？"
2. **查看回复**：系统会从医疗知识库中检索相关信息，结合大语言模型生成回答
3. **多轮对话**：系统支持基于上下文的多轮对话，可以追问或者深入讨论某个问题
4. **更新API密钥**：如果需要更新API密钥，点击右上角"设置API密钥"按钮

## API文档

启动后端服务器后，可以访问 http://localhost:8000/docs 查看API文档，包括：

- `/api/chat` - 非流式聊天接口
- `/api/chat_stream` - 流式聊天接口（SSE）
- `/api/updateApiKey` - 更新API密钥
- `/api/conversations` - 对话管理接口

## 项目扩展

- **支持更多模型**：可以扩展支持更多的大语言模型
- **自定义知识库**：更新`full1.md`文件或添加更多知识文档
- **用户认证**：添加用户登录和权限管理
- **日志分析**：添加详细的用户对话日志分析功能

## 贡献指南

欢迎为项目做出贡献！请遵循以下步骤：

1. Fork 本仓库
2. 创建你的特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交你的更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启一个 Pull Request

## 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 致谢

- [LangChain](https://github.com/langchain-ai/langchain) - LLM应用框架
- [FastAPI](https://fastapi.tiangolo.com/) - 高性能API框架
- [React](https://reactjs.org/) - 用户界面库
- [通义千问](https://dashscope.aliyun.com/) - 大语言模型服务