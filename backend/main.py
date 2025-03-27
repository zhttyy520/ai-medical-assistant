from fastapi import FastAPI, Request, Depends, status, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import os
import json
import asyncio
import uuid
import base64
from PIL import Image
import io
import aiofiles
import numpy as np
import requests
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from dotenv import load_dotenv
from dashscope import ImageSynthesis

# LangChain导入
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_community.chat_models import ChatTongyi
from langchain.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings.dashscope import DashScopeEmbeddings
from langchain_chroma import Chroma
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

# 加载环境变量
load_dotenv()

# 获取DashScope API Key
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
# 设置API密钥
os.environ["DASHSCOPE_API_KEY"] = DASHSCOPE_API_KEY
print(f"使用DashScope API Key: {DASHSCOPE_API_KEY[:8]}...（已隐藏部分）")

# 创建图片存储目录
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
print(f"图片上传目录: {UPLOAD_DIR}")

try:
    embeddings = DashScopeEmbeddings(
        model="text-embedding-v1",  # 使用阿里云提供的文本嵌入模型
    )
    print("DashScope嵌入模型初始化成功")
except Exception as e:
    print(f"DashScope嵌入模型初始化失败: {str(e)}")
    embeddings = None

# 初始化FastAPI应用
app = FastAPI(title="AI医疗助手")

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源，生产环境中应当限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 数据模型
class Message(BaseModel):
    role: str
    content: str
    timestamp: Optional[str] = None
    image_url: Optional[str] = None  # 添加图片URL字段

class ChatRequest(BaseModel):
    message: str
    chat_history: Optional[List[Message]] = []

class MultiModalRequest(BaseModel):
    message: str
    chat_history: Optional[List[Message]] = []
    image_data: Optional[str] = None  # Base64编码的图片数据

class StreamingCallbackHandler:
    """用于处理流式回调的处理器"""
    
    def __init__(self):
        self.queue = asyncio.Queue()
        self.done = asyncio.Event()
        
    async def on_llm_new_token(self, token: str, **kwargs) -> None:
        """当新的token生成时将它放入队列"""
        await self.queue.put(token)
    
    async def on_llm_end(self, response: Any, **kwargs) -> None:
        """当LLM结束时设置事件标志"""
        self.done.set()
    
    async def on_llm_error(self, error: Exception, **kwargs) -> None:
        """处理错误"""
        await self.queue.put(f"Error: {str(error)}")
        self.done.set()

# 内存存储对话历史
conversation_store = {}

# 初始化RAG组件
def initialize_rag():
    # 如果嵌入模型初始化失败，则不初始化RAG
    if embeddings is None:
        print("由于嵌入模型初始化失败，RAG组件无法初始化")
        return None
        
    # 加载本地 Markdown 文件
    try:
        # 尝试找到文件路径
        possible_file_paths = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "full1.md"),
            "./full1.md",
        ]
        
        file_path = None
        for path in possible_file_paths:
            if os.path.exists(path):
                file_path = path
                break
                
        if not file_path:
            print(f"错误: 未找到知识库文件")
            return None
            
        print(f"找到知识库文件: {file_path}")
        
        # 加载文档
        loader = TextLoader(file_path, encoding='utf-8')
        documents = loader.load()
        
        if not documents or len(documents) == 0:
            print("警告: 文档加载成功但内容为空")
            return None
            
        print(f"成功加载文档，共有 {len(documents)} 个文档段落")
        
        # 分割文档
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=200)
        all_splits = text_splitter.split_documents(documents)
        
        if not all_splits or len(all_splits) == 0:
            print("警告: 文档分割后内容为空")
            return None
            
        print(f"文档分割完成，共有 {len(all_splits)} 个文本块")
        
        # 创建向量存储
        try:
            vectorstore = Chroma.from_documents(documents=all_splits, embedding=embeddings)
            print("成功创建向量存储")
            return vectorstore
        except Exception as e:
            print(f"创建向量存储失败: {str(e)}")
            return None
            
    except Exception as e:
        print(f"初始化RAG组件失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

# 格式化文档
def format_docs(docs):
    if not docs:
        return ""
    return "\n\n".join(doc.page_content for doc in docs)

# 修改用于RAG的提示模板，增强Markdown支持和添加历史上下文
RAG_TEMPLATE = """你是一位专业的AI医疗助手，会提供准确、有帮助的医疗健康信息。
请基于以下参考信息、聊天历史（如果有的话）以及你的专业知识回答用户的问题：

参考信息:
{context}

{history_context}

用户问题: {question}

请遵循以下回答规则：
1. 使用Markdown格式化你的回答，使其更易于阅读，例如使用标题、列表、粗体等
2. 如有医学专业术语，可以使用斜体或加粗标记，并简单解释其含义
3. 如果是重要的健康警告或注意事项，请使用引用块标记
4. 如有必要，使用表格呈现对比信息或数据
5. 对于需要强调的内容，可以使用**加粗**格式
6. 提供清晰的结构，使用标题（#、##）分隔不同部分
7. 对于列表类信息，使用有序或无序列表格式展示
8. 如果建议就医，请用**加粗格式**强调
9. 根据聊天历史提供连贯性的回答，避免重复已经提供过的信息

回答时，保持专业、同理心和礼貌，但不要过度承诺医疗效果。始终提醒用户在有疑虑时咨询专业医生。
"""

# 修改用于普通问题的提示模板，增强Markdown支持
DEFAULT_TEMPLATE = """你是一位专业的AI医疗助手，名为"AI医疗助手"。你的主要职责是提供医疗健康相关的基础信息咨询服务。

用户问题: {question}

请遵循以下回答规则：
1. 使用Markdown格式化你的回答，使其更易于阅读，例如使用标题、列表、粗体等
2. 如有医学专业术语，可以使用斜体或加粗标记，并简单解释其含义
3. 如果是重要的健康警告或注意事项，请使用引用块标记
4. 如有必要，使用表格呈现对比信息或数据
5. 对于需要强调的内容，可以使用**加粗**格式
6. 提供清晰的结构，使用标题（#、##）分隔不同部分
7. 对于列表类信息，使用有序或无序列表格式展示
8. 如果建议就医，请用**加粗格式**强调

回答时，请注意：
- 保持专业、准确、有帮助且有同理心
- 清晰说明你不能提供诊断、处方或替代专业医疗建议
- 对于严重症状或紧急情况，建议用户立即就医
- 禁止讨论或建议未经批准的治疗方法
- 不要过度承诺任何治疗的效果
- 对未知问题，坦诚承认自己的局限性

回答：
"""

# 系统提示修改为更加强调Markdown格式输出
SYSTEM_PROMPT = """你是一位专业的AI医疗助手，提供准确、科学的医疗健康信息。请注意：
1. 使用Markdown格式组织回答，包括标题、列表、表格等
2. 医学专业术语使用**加粗**或*斜体*并简要解释
3. 健康警告使用> 引用块格式
4. 结构化信息使用清晰的标题层级和列表
5. 重要建议使用加粗标记
6. 你不是医生，不能诊断或提供个人化医疗建议
7. 对于紧急情况，建议用户立即就医

始终保持专业、准确和有帮助的态度。"""

general_prompt = ChatPromptTemplate.from_template(DEFAULT_TEMPLATE)
rag_prompt = ChatPromptTemplate.from_template(RAG_TEMPLATE)

# 初始化智能问答组件
# vectorstore = initialize_rag()
vectorstore = None
if vectorstore:
    retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
else:
    retriever = None

# 智能回答函数
async def smart_answer(question, model, chat_history=None):
    """
    根据问题和聊天历史生成智能回答
    
    Args:
        question: 用户的当前问题
        model: 要使用的语言模型
        chat_history: 可选的聊天历史记录列表
        
    Returns:
        生成的回答文本
    """
    try:
        # 准备消息列表，始终以系统提示开始
        messages = [
            SystemMessage(content=SYSTEM_PROMPT)
        ]
        
        # 添加聊天历史到消息列表
        if chat_history:
            # 限制历史消息数量，保留最近的10条
            recent_history = chat_history[-10:] if len(chat_history) > 10 else chat_history
            for msg in recent_history:
                # 处理不同类型的消息对象
                if isinstance(msg, dict):
                    # 如果是字典类型（来自JSON）
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                elif hasattr(msg, "role") and hasattr(msg, "content"):
                    # 如果是Message类对象
                    role = msg.role
                    content = msg.content
                else:
                    # 跳过无法处理的消息
                    print(f"警告: 无法处理的消息类型: {type(msg)}")
                    continue
                
                # 根据角色添加适当的消息
                if role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))
        
        # 如果没有成功初始化检索器，则只使用模型直接回答
        if not retriever:
            # 添加当前问题
            messages.append(HumanMessage(content=question))
            print(f"无RAG，使用历史记录生成回答，历史消息数量: {len(messages)-1}")
            try:
                return model.invoke(messages).content
            except Exception as e:
                print(f"模型调用失败: {str(e)}")
                return _generate_fallback_response(question, chat_history)
        
        # 尝试检索相关文档
        try:
            docs = retriever.invoke(question)
        except Exception as e:
            print(f"检索器调用失败: {str(e)}")
            # 添加当前问题
            messages.append(HumanMessage(content=question))
            try:
                return model.invoke(messages).content
            except Exception as e2:
                print(f"模型调用失败: {str(e2)}")
                return _generate_fallback_response(question, chat_history)
        
        if docs:
            # 如果找到相关文档，准备上下文
            context = format_docs(docs)
            print(f"找到相关文档，使用RAG模板生成回答，文档数量: {len(docs)}")
            
            # 构建带有历史上下文的提示
            history_context = ""
            if chat_history and len(chat_history) > 0:
                # 创建历史上下文字符串
                history_context = "\n\n聊天历史:\n"
                # 只使用最近的5条消息作为上下文
                recent_history = chat_history[-5:] if len(chat_history) > 5 else chat_history
                for msg in recent_history:
                    # 处理不同类型的消息对象
                    if isinstance(msg, dict):
                        # 如果是字典类型（来自JSON）
                        role = msg.get("role", "")
                        content = msg.get("content", "")
                    elif hasattr(msg, "role") and hasattr(msg, "content"):
                        # 如果是Message类对象
                        role = msg.role
                        content = msg.content
                    else:
                        # 跳过无法处理的消息
                        continue
                        
                    role_name = "用户" if role == "user" else "AI医疗助手"
                    history_context += f"{role_name}: {content}\n"
            
            # 组合上下文和历史到RAG提示
            rag_chain = (
                rag_prompt 
                | model 
                | StrOutputParser()
            )
            try:
                return rag_chain.invoke({
                    "context": context, 
                    "question": question,
                    "history_context": history_context
                })
            except Exception as e:
                print(f"RAG链调用失败: {str(e)}")
                # 如果RAG链失败，尝试直接使用模型
                messages.append(HumanMessage(content=question))
                try:
                    return model.invoke(messages).content
                except Exception as e2:
                    print(f"模型调用失败: {str(e2)}")
                    return _generate_fallback_response(question, chat_history)
        else:
            # 如果没有找到相关文档，添加当前问题到消息列表
            messages.append(HumanMessage(content=question))
            print(f"无相关文档，使用历史记录生成回答，历史消息数量: {len(messages)-1}")
            try:
                return model.invoke(messages).content
            except Exception as e:
                print(f"模型调用失败: {str(e)}")
                return _generate_fallback_response(question, chat_history)
    except Exception as e:
        print(f"智能回答生成出错: {str(e)}")
        return _generate_fallback_response(question, chat_history)

# 后备回答生成函数
def _generate_fallback_response(question, chat_history=None):
    """当API调用失败时生成的后备回答"""
    # 检查问题是否询问之前的对话内容
    memory_keywords = ["之前", "刚才", "上面", "之前问", "刚问", "之前聊", "刚才说", "刚刚问"]
    history_question = any(keyword in question for keyword in memory_keywords)
    
    if history_question and chat_history and len(chat_history) > 0:
        # 尝试从历史记录中提取最近的1-2条用户消息
        recent_user_msgs = []
        for msg in reversed(chat_history):
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                recent_user_msgs.append(content)
            elif hasattr(msg, "role") and msg.role == "user":
                content = msg.content
                recent_user_msgs.append(content)
            if len(recent_user_msgs) >= 2:
                break
        
        if recent_user_msgs:
            history_summary = "、".join(recent_user_msgs[:2][::-1])
            return f"""根据我的记忆，您之前问了关于"{history_summary}"的问题。

很抱歉，我目前遇到了一些技术问题，无法提供完整的回答。请稍后再试，或者重新表述您的问题，我会尽力帮助您。"""
    
    # 通用后备回答
    return """很抱歉，我目前遇到了一些技术问题，无法处理您的请求。这可能是由于以下原因：

1. 服务器负载过高
2. API调用限制
3. 网络连接问题

请稍后再试，或者重新表述您的问题，我会尽力帮助您。如果问题持续存在，请联系技术支持。

感谢您的理解。"""

# 获取对话ID的依赖
def get_conversation_id(request: Request) -> str:
    """从请求中获取会话ID, 如果没有则创建新的"""
    # 先尝试从查询参数获取会话ID
    conversation_id = request.query_params.get("conversation_id")
    
    # 如果查询参数中没有，再尝试从头部获取
    if not conversation_id:
        conversation_id = request.headers.get("X-Conversation-ID")
    
    # 如果没有找到会话ID，生成一个新的
    if not conversation_id:
        conversation_id = str(datetime.now().timestamp())
    
    # 如果是新的会话ID，初始化
    if conversation_id not in conversation_store:
        print(f"创建新会话: {conversation_id}")
        conversation_store[conversation_id] = {
            "messages": []
        }
    
    return conversation_id

@app.get("/")
async def root():
    """健康检查端点"""
    current_time = datetime.now().isoformat()
    return {
        "status": "ok", 
        "message": "AI医疗助手系统正在运行",
        "version": "1.0.0",
        "rag_status": "enabled" if retriever else "disabled",
        "timestamp": current_time
    }

@app.post("/api/chat")
async def chat(
    request: ChatRequest, 
    conversation_id: str = Depends(get_conversation_id),
    request_raw: Request = None
):
    """非流式聊天API端点"""
    try:
        # 打印接收到的请求信息
        print(f"非流式请求 - 消息: '{request.message}', 会话ID: {conversation_id}")
        
        try:
            model = ChatTongyi(model_name="qwen-turbo")
        except Exception as e:
            print(f"模型初始化失败: {str(e)}")
            # 返回错误响应
            return {
                "response": _generate_fallback_response(request.message, request.chat_history),
                "conversation_id": conversation_id,
                "error": f"模型初始化失败: {str(e)}"
            }
        
        # 处理聊天历史，可能是Pydantic模型或已经是字典列表
        chat_history = []
        if request.chat_history:
            # 转换Message对象为字典
            for msg in request.chat_history:
                if isinstance(msg, dict):
                    chat_history.append(msg)
                elif hasattr(msg, "role") and hasattr(msg, "content"):
                    chat_history.append({
                        "role": msg.role,
                        "content": msg.content,
                        "timestamp": msg.timestamp if hasattr(msg, "timestamp") else None
                    })
        
        # 如果是新的会话，获取聊天历史
        current_chat_history = []
        if conversation_id in conversation_store:
            current_chat_history = conversation_store[conversation_id]["messages"]
        
        # 合并当前会话历史和请求中的历史 - 优先使用请求中的历史，如果没有则使用服务器存储的历史
        if not chat_history and current_chat_history:
            chat_history = current_chat_history
        
        # 打印历史长度
        print(f"使用的历史消息数量: {len(chat_history)}")
        
        # 使用智能回答函数处理请求
        response_content = await smart_answer(request.message, model, chat_history)
        print(f"生成的回答: '{response_content[:50]}...'(长度:{len(response_content)})")
        
        # 更新会话消息列表
        conversation_store[conversation_id]["messages"].append({
            "role": "user",
            "content": request.message,
            "timestamp": datetime.now().isoformat()
        })
        conversation_store[conversation_id]["messages"].append({
            "role": "assistant",
            "content": response_content,
            "timestamp": datetime.now().isoformat()
        })
        
        return {
            "response": response_content,
            "conversation_id": conversation_id
        }
        
    except Exception as e:
        error_msg = f"聊天API端点错误: {str(e)}"
        print(error_msg)
        print(f"错误详情: {type(e).__name__}, {e.__traceback__.tb_lineno}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": str(e)}
        )

@app.post("/api/chat/stream")
@app.get("/api/chat/stream")
async def chat_stream(
    request: ChatRequest = None, 
    conversation_id: str = Depends(get_conversation_id),
    request_raw: Request = None
):
    """流式聊天API端点 - 支持POST和GET请求"""
    try:
        # 如果是GET请求，尝试从查询参数获取消息，用于EventSource
        message = ""
        chat_history = []
        
        if request_raw and request_raw.method == "GET":
            # 从会话ID尝试获取最后一条用户消息
            if conversation_id in conversation_store and conversation_store[conversation_id]["messages"]:
                messages = conversation_store[conversation_id]["messages"]
                chat_history = messages.copy()  # 保存整个历史
                user_messages = [msg for msg in messages if msg["role"] == "user"]
                if user_messages:
                    message = user_messages[-1]["content"]
                    print(f"GET请求使用会话 {conversation_id} 的最后一条用户消息: '{message}'")
                    print(f"聊天历史包含 {len(chat_history)} 条消息")
                else:
                    print(f"警告: 会话 {conversation_id} 没有用户消息")
            else:
                print(f"警告: 未找到会话 {conversation_id} 或会话为空")
        elif request:
            message = request.message
            
            # 处理聊天历史，可能是Pydantic模型或已经是字典列表
            if request.chat_history:
                # 转换Message对象为字典
                chat_history = []
                for msg in request.chat_history:
                    if isinstance(msg, dict):
                        chat_history.append(msg)
                    elif hasattr(msg, "role") and hasattr(msg, "content"):
                        chat_history.append({
                            "role": msg.role,
                            "content": msg.content,
                            "timestamp": msg.timestamp if hasattr(msg, "timestamp") else None
                        })
            
            print(f"POST请求接收到的消息: '{message}'")
            print(f"消息历史长度: {len(chat_history)}")
        else:
            print("警告: 未能获取到消息内容，使用空字符串")
        
        # 打印接收到的请求信息
        print(f"处理流式请求 - 消息: '{message}', 会话ID: {conversation_id}")
        print(f"请求方法: {request_raw.method if request_raw else 'POST'}")
        
        # 创建一个异步生成器来流式传输聊天响应
        async def event_generator():
            # 在生成器内部声明非局部变量，确保可以访问外部作用域的变量
            nonlocal message, chat_history, conversation_id
            
            try:
                if not message:
                    # 如果没有消息，发送简单提示
                    yield {
                        "event": "message",
                        "data": "请"
                    }
                    await asyncio.sleep(0.05)
                    yield {
                        "event": "message",
                        "data": "输"
                    }
                    await asyncio.sleep(0.05)
                    yield {
                        "event": "message",
                        "data": "入"
                    }
                    await asyncio.sleep(0.05)
                    yield {
                        "event": "message",
                        "data": "您"
                    }
                    await asyncio.sleep(0.05)
                    yield {
                        "event": "message",
                        "data": "的"
                    }
                    await asyncio.sleep(0.05)
                    yield {
                        "event": "message",
                        "data": "问"
                    }
                    await asyncio.sleep(0.05)
                    yield {
                        "event": "message",
                        "data": "题"
                    }
                    
                    # 发送完成事件
                    yield {
                        "event": "done",
                        "data": json.dumps({"message": "Stream completed", "conversation_id": conversation_id})
                    }
                    return
                
                print(f"开始处理流式响应...")
                try:
                    model = ChatTongyi(model_name="qwen-turbo")
                    print("模型初始化成功")
                except Exception as e:
                    # 如果模型初始化失败，发送错误信息
                    error_msg = f"模型初始化失败: {str(e)}"
                    print(error_msg)
                    
                    # 生成后备回答
                    fallback_response = _generate_fallback_response(message, chat_history)
                    
                    # 模拟流式输出后备回答
                    for char in fallback_response:
                        yield {
                            "event": "message",
                            "data": char
                        }
                        await asyncio.sleep(0.01)
                    
                    # 发送完成事件
                    yield {
                        "event": "done",
                        "data": json.dumps({"message": "Stream completed with fallback", "conversation_id": conversation_id})
                    }
                    
                    # 更新会话记录（如果是POST请求）
                    if request_raw and request_raw.method == "POST" and message:
                        # 记录用户消息
                        conversation_store[conversation_id]["messages"].append({
                            "role": "user",
                            "content": message,
                            "timestamp": datetime.now().isoformat()
                        })
                        # 记录助手消息
                        conversation_store[conversation_id]["messages"].append({
                            "role": "assistant", 
                            "content": fallback_response,
                            "timestamp": datetime.now().isoformat()
                        })
                    
                    return
                
                # 如果是新的会话，获取聊天历史
                current_chat_history = []
                if conversation_id in conversation_store:
                    current_chat_history = conversation_store[conversation_id]["messages"]
                
                # 合并当前会话历史和请求中的历史 - 优先使用请求中的历史，如果没有则使用服务器存储的历史
                if not chat_history and current_chat_history:
                    chat_history = current_chat_history
                
                # 打印历史长度
                print(f"使用的历史消息数量: {len(chat_history)}")
                
                # 获取完整回答
                print(f"调用smart_answer生成回答...")
                full_response = await smart_answer(message, model, chat_history)
                print(f"生成的完整回答: '{full_response[:50]}...'(长度:{len(full_response)})")
                
                # 只有POST请求才记录聊天历史
                if request_raw and request_raw.method == "POST":
                    # 记录用户消息
                    conversation_store[conversation_id]["messages"].append({
                        "role": "user",
                        "content": message,
                        "timestamp": datetime.now().isoformat()
                    })
                
                # 模拟流式输出 - 将整个回答按字符分割
                print(f"开始发送流式响应字符...")
                char_count = 0
                for char in full_response:
                    # 直接发送字符，不包装在JSON对象中
                    yield {
                        "event": "message",
                        "data": char
                    }
                    char_count += 1
                    # 每100个字符打印一次状态
                    if char_count % 100 == 0:
                        print(f"已发送 {char_count} 个字符...")
                    # 添加小延迟使效果更自然
                    await asyncio.sleep(0.01)
                
                print(f"字符发送完成，共 {char_count} 个字符")
                
                # 只有POST请求才记录聊天历史
                if request_raw and request_raw.method == "POST":
                    # 更新会话消息列表
                    conversation_store[conversation_id]["messages"].append({
                        "role": "assistant",
                        "content": full_response,
                        "timestamp": datetime.now().isoformat()
                    })
                
                # 发送完成事件，包含会话ID
                completion_data = {
                    "message": "Stream completed", 
                    "conversation_id": conversation_id
                }
                yield {
                    "event": "done",
                    "data": json.dumps(completion_data)
                }
                print(f"发送完成事件: {completion_data}")
                
            except Exception as e:
                error_msg = f"流式响应错误: {str(e)}"
                print(error_msg)
                print(f"错误详情: {type(e).__name__}, {e.__traceback__.tb_lineno}")
                yield {
                    "event": "error",
                    "data": json.dumps({"error": str(e)})
                }
        
        # 使用EventSourceResponse正确构造SSE响应
        print("创建EventSourceResponse...")
        response = EventSourceResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive", 
                "X-Accel-Buffering": "no",  # 禁用Nginx缓冲
                "Access-Control-Allow-Origin": "*",  # 允许跨域
            }
        )
        print("返回EventSourceResponse")
        return response
        
    except Exception as e:
        error_msg = f"流式聊天API端点错误: {str(e)}"
        print(error_msg)
        print(f"错误详情: {type(e).__name__}, {e.__traceback__.tb_lineno}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": str(e)}
        )

@app.get("/api/history/{conversation_id}")
async def get_history(conversation_id: str):
    """获取特定会话的历史记录"""
    if conversation_id not in conversation_store:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "Conversation not found"}
        )
    
    return {
        "history": conversation_store[conversation_id]["messages"],
        "conversation_id": conversation_id
    }

# 保存上传的图片
async def save_uploaded_file(file: UploadFile) -> str:
    # 生成唯一文件名
    file_ext = os.path.splitext(file.filename)[1] if file.filename else ".jpg"
    file_name = f"{uuid.uuid4()}{file_ext}"
    file_path = os.path.join(UPLOAD_DIR, file_name)
    
    # 保存文件
    async with aiofiles.open(file_path, 'wb') as out_file:
        # 读取并写入文件内容
        content = await file.read()
        await out_file.write(content)
    
    return file_path

# 使用DashScope API进行多模态请求
async def call_dashscope_multimodal(text: str, image_path: str, history: List[Dict[str, str]] = None) -> str:
    try:
        print(f"开始处理多模态请求 - 文本: '{text}', 图片: '{image_path}'")
        
        # 直接使用 DashScope API 而不通过 LangChain
        import dashscope
        from dashscope import MultiModalConversation
        
        # 读取图片为base64
        with open(image_path, "rb") as img_file:
            image_content = base64.b64encode(img_file.read()).decode('utf-8')
        
        # 添加系统消息
        system_message = {
            "role": "system",
            "content": [
                {
                    "text": """你是一位专业的医疗助手，擅长分析医学图像和回答医疗健康相关问题。
请用简洁专业的语言回答问题，使用Markdown格式美化回复，对于医学专业术语进行解释。
重要：请确保你只回答用户当前的问题，而不是之前的问题。
请分析用户提供的图像，并根据图像内容和用户的问题提供专业的医疗建议。"""
                }
            ]
        }
        
        # 转换历史消息格式
        formatted_history = []
        if history and len(history) > 0:
            print(f"添加{len(history)}条历史消息")
            for msg in history:
                if msg["role"] == "user":
                    formatted_history.append({
                        "role": "user",
                        "content": [{"text": msg["content"]}]
                    })
                elif msg["role"] == "assistant":
                    formatted_history.append({
                        "role": "assistant",
                        "content": [{"text": msg["content"]}]
                    })
        
        # 构建当前请求的多模态消息
        current_message = {
            "role": "user",
            "content": [
                {
                    "text": text
                },
                {
                    "image": f"data:image/jpeg;base64,{image_content}"
                }
            ]
        }
        
        # 如果有历史消息，添加当前消息到历史
        messages = [system_message] + formatted_history + [current_message]
        
        print(f"准备的消息数量: {len(messages)}")
        
        # 设置API密钥
        dashscope.api_key = DASHSCOPE_API_KEY
        
        # 调用多模态模型
        response = MultiModalConversation.call(
            model='qwen-vl-plus',
            messages=messages,
            stream=True,
            result_format='message',  # 使用消息格式
            temperature=0.7,
            max_tokens=1000,
        )
        
        print(f"API调用状态码: {response.status_code}")
        print(f"API调用请求ID: {response.request_id}")
        
        # 检查响应
        if response.status_code == 200:
            # 提取文本内容
            response_message = response.output.choices[0].message
            print(f"响应角色: {response_message.role}")
            
            # 检查内容类型
            if isinstance(response_message.content, list):
                # 从多模态响应中提取文本
                text_parts = []
                for content_item in response_message.content:
                    if isinstance(content_item, dict) and 'text' in content_item:
                        text_parts.append(content_item['text'])
                response_text = "".join(text_parts)
            else:
                # 如果是字符串或其他类型
                response_text = str(response_message.content)
            
            print(f"多模态模型返回的响应: '{response_text[:100]}...' (长度: {len(response_text)})")
            return response_text
        else:
            error_msg = f"API调用失败: {response.status_code}, {response.message}"
            print(error_msg)
            return f"处理图片时出错: {error_msg}"
    
    except Exception as e:
        error_msg = f"调用多模态API出错: {str(e)}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        return f"处理图片时出错: {str(e)}"

# 新增的多模态聊天API端点（上传表单版本）
@app.post("/api/chat/multimodal")
async def chat_multimodal(
    message: str = Form(...),
    file: UploadFile = File(...),
    conversation_id: str = Depends(get_conversation_id)
):
    try:
        print(f"收到多模态表单请求 - 文本: '{message}', 图片: {file.filename}, 会话ID: {conversation_id}")
        
        # 保存上传的图片
        file_path = await save_uploaded_file(file)
        print(f"图片已保存到: {file_path}")
        
        # 获取历史消息
        history = []
        if conversation_id in conversation_store:
            # 获取最近的对话历史（最多10条）
            history = conversation_store[conversation_id]["messages"][-10:]
            print(f"获取到会话历史, 共{len(history)}条消息")
        
        # 转换为模型可用的格式
        model_history = []
        for msg in history:
            if msg["role"] in ["user", "assistant"]:
                # 只添加文本消息到历史记录，不添加图片
                model_history.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
        
        print(f"准备调用多模态模型, 文本: '{message}', 历史消息: {len(model_history)}条")
        
        # 调用多模态模型
        response_text = await call_dashscope_multimodal(message, file_path, model_history)
        print(f"多模态响应: '{response_text[:100]}...' (长度: {len(response_text)})")
        
        # 记录消息到会话历史
        current_time = datetime.now().isoformat()
        
        # 记录用户消息（带图片）
        user_message = {
            "role": "user",
            "content": message,
            "timestamp": current_time,
            "image_url": file_path  # 存储图片路径
        }
        conversation_store[conversation_id]["messages"].append(user_message)
        
        # 记录助手响应
        assistant_message = {
            "role": "assistant",
            "content": response_text,
            "timestamp": datetime.now().isoformat()
        }
        conversation_store[conversation_id]["messages"].append(assistant_message)
        
        return {
            "response": response_text,
            "conversation_id": conversation_id
        }
    
    except Exception as e:
        print(f"多模态聊天错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": str(e)}
        )

# 新增的多模态聊天API端点（JSON版本，接受base64图片数据）
@app.post("/api/chat/multimodal-json")
async def chat_multimodal_json(
    request: MultiModalRequest,
    conversation_id: str = Depends(get_conversation_id)
):
    try:
        print(f"收到多模态JSON请求 - 文本: '{request.message}', 会话ID: {conversation_id}")
        
        if not request.image_data:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "未提供图片数据"}
            )
        
        # 解码并保存base64图片
        try:
            # 处理 data URI 前缀
            base64_data = request.image_data
            
            # 如果包含 data URI 格式，提取 base64 部分
            if ';base64,' in base64_data:
                base64_data = base64_data.split(';base64,')[1]
            elif ',' in base64_data:  # 简单格式 data:,base64数据
                base64_data = base64_data.split(',')[1]
                
            # 解码 base64 数据
            try:
                image_bytes = base64.b64decode(base64_data)
            except Exception as decode_err:
                print(f"Base64解码失败: {str(decode_err)}")
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"error": f"Base64解码失败: {str(decode_err)}"}
                )
            
            # 验证解码后的数据是否为有效的图像
            try:
                from PIL import Image
                image = Image.open(io.BytesIO(image_bytes))
                image_format = image.format.lower() if image.format else "jpeg"
                print(f"图片格式: {image_format}, 尺寸: {image.size}")
            except Exception as img_err:
                print(f"图片无效: {str(img_err)}")
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"error": f"提供的数据不是有效的图片: {str(img_err)}"}
                )
            
            # 生成唯一文件名并保存图片
            file_name = f"{uuid.uuid4()}.{image_format}"
            file_path = os.path.join(UPLOAD_DIR, file_name)
            
            # 保存图片
            with open(file_path, 'wb') as f:
                f.write(image_bytes)
                
            print(f"Base64图片已保存到: {file_path}")
        except Exception as e:
            print(f"保存base64图片失败: {str(e)}")
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": f"图片处理失败: {str(e)}"}
            )
        
        # 处理聊天历史
        chat_history = []
        if request.chat_history:
            # 安全地转换Message对象为字典
            for msg in request.chat_history:
                try:
                    # 如果msg已经是字典
                    if isinstance(msg, dict):
                        # 确保有role和content字段
                        if "role" in msg and "content" in msg:
                            chat_history.append(msg)
                        else:
                            print(f"警告: 消息缺少必要字段 {msg}")
                    # 如果msg是Pydantic模型
                    elif hasattr(msg, "role") and hasattr(msg, "content"):
                        chat_history.append({
                            "role": msg.role,
                            "content": msg.content,
                            "timestamp": msg.timestamp if hasattr(msg, "timestamp") else datetime.now().isoformat()
                        })
                    else:
                        print(f"警告: 无法识别的消息类型 {type(msg)}")
                except Exception as msg_error:
                    print(f"处理消息时出错: {str(msg_error)}")
                    # 继续处理下一条消息
        
        # 如果请求的历史为空，获取服务器存储的历史
        if not chat_history and conversation_id in conversation_store:
            chat_history = conversation_store[conversation_id]["messages"][-10:]
            print(f"使用服务器存储的历史记录, 共{len(chat_history)}条消息")
        
        # 转换为模型可用的格式
        model_history = []
        for msg in chat_history:
            try:
                if isinstance(msg, dict) and "role" in msg and "content" in msg:
                    if msg["role"] in ["user", "assistant"]:
                        # 只添加文本消息到历史记录，不添加图片
                        model_history.append({
                            "role": msg["role"],
                            "content": msg["content"]
                        })
                else:
                    print(f"跳过不符合格式的消息: {msg}")
            except Exception as e:
                print(f"处理历史消息时出错: {str(e)}")
        
        print(f"准备调用多模态模型, 文本: '{request.message}', 历史消息: {len(model_history)}条")
        
        # 调用多模态模型 - 使用当前的请求消息
        response_text = await call_dashscope_multimodal(request.message, file_path, model_history)
        
        # 确保响应是字符串格式
        if not isinstance(response_text, str):
            print(f"警告: 响应不是字符串类型, 而是 {type(response_text)}")
            if response_text is None:
                response_text = "图像处理完成，但未能生成回复。"
            else:
                try:
                    # 尝试将非字符串响应转换为字符串
                    if isinstance(response_text, dict):
                        if 'content' in response_text:
                            response_text = str(response_text['content'])
                        elif 'text' in response_text:
                            response_text = str(response_text['text'])
                        else:
                            response_text = json.dumps(response_text, ensure_ascii=False)
                    elif isinstance(response_text, list):
                        # 尝试提取列表中的文本内容
                        text_items = []
                        for item in response_text:
                            if isinstance(item, str):
                                text_items.append(item)
                            elif isinstance(item, dict) and 'text' in item:
                                text_items.append(str(item['text']))
                        
                        if text_items:
                            response_text = '\n'.join(text_items)
                        else:
                            response_text = json.dumps(response_text, ensure_ascii=False)
                    else:
                        response_text = str(response_text)
                except Exception as text_err:
                    print(f"转换响应为字符串时出错: {str(text_err)}")
                    response_text = "收到响应，但格式无法处理。"
        
        print(f"多模态响应: '{response_text[:100]}...' (长度: {len(response_text)})")
        
        # 记录消息到会话历史
        current_time = datetime.now().isoformat()
        
        # 记录用户消息（带图片）
        user_message = {
            "role": "user",
            "content": request.message,
            "timestamp": current_time,
            "image_url": file_path  # 存储图片路径
        }
        conversation_store[conversation_id]["messages"].append(user_message)
        
        # 记录助手响应
        assistant_message = {
            "role": "assistant",
            "content": response_text,
            "timestamp": datetime.now().isoformat()
        }
        conversation_store[conversation_id]["messages"].append(assistant_message)
        
        return {
            "response": response_text,
            "conversation_id": conversation_id
        }
    
    except Exception as e:
        print(f"多模态JSON请求错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": str(e)}
        )

# 定义文生图请求模型类
class TextToImageRequest(BaseModel):
    prompt: str  # 图像生成提示词
    negative_prompt: Optional[str] = None  # 负面提示词，可选
    n: Optional[int] = 1  # 生成图片数量，默认1张
    size: Optional[str] = "1024*1024"  # 图片尺寸，默认1024*1024

# 文生图API端点
@app.post("/api/text2image")
async def text2image(
    request: TextToImageRequest,
    conversation_id: str = Depends(get_conversation_id)
):
    """生成图像的API端点"""
    try:
        print(f"收到文生图请求 - 提示词: '{request.prompt}', 会话ID: {conversation_id}")
        
        # 调用文生图API
        rsp = ImageSynthesis.call(
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            model="wanx2.1-t2i-turbo",  # 使用wanx2.1-t2i-turbo模型
            prompt=request.prompt,
            negative_prompt=request.negative_prompt,
            n=request.n,
            size=request.size
        )
        print('文生图API响应:', rsp)
        
        # 处理响应
        if rsp.status_code == 200:
            # 收集大模型返回的原始图片URL
            original_image_urls = []
            
            for result in rsp.output.results:
                # 直接使用大模型返回的URL
                original_image_urls.append(result.url)
                print(f"大模型生成的图片URL: {result.url}")
            
            # 记录到会话历史
            current_time = datetime.now().isoformat()
            
            # 记录用户请求
            user_message = {
                "role": "user",
                "content": f"请根据以下描述生成图片: {request.prompt}",
                "timestamp": current_time
            }
            conversation_store[conversation_id]["messages"].append(user_message)
            
            # 记录系统响应
            if original_image_urls:
                assistant_message = {
                    "role": "assistant",
                    "content": f"已根据您的描述生成图片: {request.prompt}",
                    "timestamp": datetime.now().isoformat(),
                    "image_url": original_image_urls[0]  # 直接使用大模型返回的URL
                }
                conversation_store[conversation_id]["messages"].append(assistant_message)
            
            # 返回结果
            return {
                "image_urls": original_image_urls,
                "conversation_id": conversation_id
            }
        else:
            error_msg = f"文生图API调用失败: {rsp.status_code}, {rsp.message}"
            print(error_msg)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"error": error_msg}
            )
            
    except Exception as e:
        print(f"文生图API请求错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": str(e)}
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True) 