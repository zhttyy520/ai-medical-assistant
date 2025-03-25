import axios from 'axios';

// 定义Message类型
export interface Message {
  role: string;
  content: string;
  timestamp?: string;
}

// API基础URL
const API_BASE_URL = 'http://localhost:8000/api';

// 定义请求类型
export interface ChatRequest {
  message: string;
  chat_history?: any[];
}

// 发送普通消息（非流式）
export async function sendMessage(
  message: string, 
  conversationId?: string,
  chatHistory?: any[]
) {
  console.log(`发送普通消息: '${message}', conversationId: ${conversationId || '新会话'}, 历史消息数: ${chatHistory?.length || 0}`);
  
  try {
    // 构建请求对象
    const request: ChatRequest = {
      message,
      chat_history: chatHistory || []
    };
    
    // 设置请求头
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    
    // 如果有会话ID，添加到URL参数
    let url = `${API_BASE_URL}/chat`;
    if (conversationId) {
      url += `?conversation_id=${conversationId}`;
    }
    
    console.log(`发送POST请求到: ${url}`);
    
    // 发送请求
    const response = await axios.post(url, request, { headers });
    
    return {
      content: response.data.response,
      conversationId: response.data.conversation_id
    };
  } catch (error) {
    console.error(`发送消息失败:`, error);
    throw error;
  }
}

interface StreamCallbacks {
  onToken: (token: string) => void;
  onComplete: (message: string, conversationId: string) => void;
  onError: (error: string) => void;
}

// 发送流式消息，使用原生EventSource
export function sendStreamMessage(
  message: string,
  callbacks: StreamCallbacks,
  conversationId?: string
): () => void {
  console.log(`开始发送流式消息: '${message}', conversationId: ${conversationId || '新会话'}`);
  
  try {
    // 构建URL - 对于EventSource必须是GET请求
    const url = new URL(`${API_BASE_URL}/chat/stream`);
    
    // 如果有会话ID，将其添加到URL中
    if (conversationId) {
      url.searchParams.append('conversation_id', conversationId);
    }
    
    console.log(`创建EventSource连接: ${url.toString()}`);
    
    // 创建EventSource实例
    const eventSource = new EventSource(url.toString());
    let responseText = '';
    
    // 监听消息事件
    eventSource.addEventListener('message', (event) => {
      try {
        console.log(`收到message事件: ${event.data}`);
        const data = JSON.parse(event.data);
        if (data.token) {
          callbacks.onToken(data.token);
          responseText += data.token;
        }
      } catch (error) {
        console.error(`解析消息事件数据失败:`, error);
      }
    });
    
    // 监听完成事件
    eventSource.addEventListener('done', (event) => {
      try {
        console.log(`收到done事件: ${event.data}`);
        const data = JSON.parse(event.data);
        eventSource.close();
        callbacks.onComplete(responseText, data.conversation_id || conversationId || '');
      } catch (error) {
        console.error(`解析完成事件数据失败:`, error);
        eventSource.close();
      }
    });
    
    // 监听错误事件
    eventSource.addEventListener('error', (event) => {
      console.error(`EventSource错误事件:`, event);
      eventSource.close();
      callbacks.onError('连接错误或中断');
    });
    
    // 监听自定义错误消息
    eventSource.addEventListener('error', (event: MessageEvent) => {
      try {
        if (event.data) {
          console.error(`收到错误消息: ${event.data}`);
          const data = JSON.parse(event.data);
          if (data.error) {
            callbacks.onError(data.error);
          }
        }
      } catch (error) {
        console.error(`解析错误事件数据失败:`, error);
      }
    });
    
    // 返回清理函数
    return () => {
      console.log('关闭EventSource连接');
      eventSource.close();
    };
  } catch (error) {
    console.error(`初始化EventSource失败:`, error);
    callbacks.onError(`连接到服务器失败: ${error}`);
    return () => {}; // 返回空清理函数
  }
}

// 同时使用POST方法发送流式消息（用于初次发送）
export function sendStreamMessagePost(
  message: string,
  callbacks: StreamCallbacks,
  conversationId?: string,
  chatHistory?: any[]
): () => void {
  console.log(`使用POST发送流式消息: '${message}', conversationId: ${conversationId || '新会话'}`);
  
  try {
    // 构建请求
    const controller = new AbortController();
    const signal = controller.signal;
    
    const requestBody = {
      message,
      chat_history: chatHistory || []
    };
    
    const requestUrl = `${API_BASE_URL}/chat/stream${conversationId ? `?conversation_id=${conversationId}` : ''}`;
    console.log(`发送POST请求: ${requestUrl}`);
    
    // 发送Fetch请求
    fetch(requestUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(requestBody),
      signal
    })
    .then(response => {
      console.log(`收到响应: ${response.body} ${response.statusText}`);
      if (!response.ok) {
        throw new Error(`HTTP错误: ${response.status}`);
      }
      if (!response.body) {
        throw new Error('响应中没有数据流');
      }
      
      // 处理响应流
      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';
      let responseText = '';
      
      function processStream(): Promise<void> {
        return reader.read().then(({ done, value }) => {
          if (done) {
            // 处理最后可能的缓冲数据
            if (buffer.trim()) {
              processBuffer(buffer);
            }
            console.log(`流结束，总内容长度: ${responseText.length}`);
            callbacks.onComplete(responseText, conversationId || '');
            return;
          }
          
          // 解码新接收的数据
          const newText = decoder.decode(value, { stream: true });
          buffer += newText;
          
          // 根据SSE格式处理缓冲区中的消息
          processBuffer(buffer);
          
          // 继续读取
          return processStream();
        });
      }
      
      function processBuffer(text: string) {
        // 按SSE格式分割缓冲区中的消息
        const messageRegex = /event: ([^\n]+)\ndata: ([^\n]+)\n\n/g;
        let match;
        let newBuffer = text;
        
        while ((match = messageRegex.exec(text)) !== null) {
          const eventType = match[1];
          const eventData = match[2];
          
          // 更新缓冲区，移除已处理的消息
          newBuffer = newBuffer.slice(match.index + match[0].length);
          
          try {
            const data = JSON.parse(eventData);
            
            if (eventType === 'message' && data.token) {
              callbacks.onToken(data.token);
              responseText += data.token;
            } else if (eventType === 'done') {
              console.log(`收到done事件: ${eventData}`);
              callbacks.onComplete(responseText, data.conversation_id || conversationId || '');
            } else if (eventType === 'error') {
              console.error(`收到错误事件: ${eventData}`);
              if (data.error) {
                callbacks.onError(data.error);
              }
            }
          } catch (error) {
            console.error(`解析事件数据失败: ${eventData}`, error);
          }
        }
        
        // 更新缓冲区为剩余未处理的部分
        buffer = newBuffer;
      }
      
      return processStream();
    })
    .catch(error => {
      console.error(`流式请求错误:`, error);
      callbacks.onError(`请求失败: ${error.message}`);
    });
    
    // 返回清理函数
    return () => {
      console.log('中止POST流式请求');
      controller.abort();
    };
  } catch (error) {
    console.error(`发送POST流式消息失败:`, error);
    callbacks.onError(`发送消息失败: ${error}`);
    return () => {}; // 返回空清理函数
  }
}

// 获取对话历史
export const getChatHistory = async (conversationId: string) => {
  const response = await axios.get(`${API_BASE_URL}/history/${conversationId}`);
  return response.data;
}; 