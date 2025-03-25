from fastapi import FastAPI, Request, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import os
import json
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
from dotenv import load_dotenv

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
if not DASHSCOPE_API_KEY:
    print("警告: 环境变量中未找到DASHSCOPE_API_KEY，尝试使用硬编码值")
    DASHSCOPE_API_KEY = "your_dashscope_api_key_here"  
    
# 设置API密钥
os.environ["DASHSCOPE_API_KEY"] = DASHSCOPE_API_KEY
print(f"使用DashScope API Key: {DASHSCOPE_API_KEY[:8]}...（已隐藏部分）")

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

class ChatRequest(BaseModel):
    message: str
    chat_history: Optional[List[Message]] = []

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
vectorstore = initialize_rag()
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True) 