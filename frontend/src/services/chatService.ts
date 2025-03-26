import axios from 'axios';

// 定义Message类型
export interface Message {
  role: string;
  content: string;
  timestamp?: string;
  image_url?: string;  // 添加图片URL字段
  isTemporary?: boolean; // 标记是否为临时消息
}

// API基础URL
const API_BASE_URL = 'http://localhost:8000/api';

// 定义请求类型
export interface ChatRequest {
  message: string;
  chat_history?: any[];
}

// 定义多模态请求类型
export interface MultiModalChatRequest {
  message: string;
  chat_history?: any[];
  image_data?: string;  // Base64编码的图片数据
}

// 发送普通消息（非流式）
export async function sendMessage(
  message: string, 
  conversationId?: string,
  chatHistory?: any[],
  useStream: boolean = false,
  onTokenReceived?: (token: string) => void
) {
  console.log(`发送消息: '${message}', conversationId: ${conversationId || '新会话'}, 历史消息数: ${chatHistory?.length || 0}, 使用流式响应: ${useStream}`);
  
  if (useStream) {
    return sendStreamMessage(message, conversationId, chatHistory, onTokenReceived);
  }
  
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

// 使用表单发送多模态消息（图片+文本）
export async function sendMultiModalMessage(
  message: string,
  imageFile: File,
  conversationId?: string,
  chatHistory?: any[]
) {
  try {
    console.log(`发送多模态消息: '${message}', 图片: ${imageFile.name}, conversationId: ${conversationId || '新会话'}, 历史消息数: ${chatHistory?.length || 0}`);
    
    // 构建FormData
    const formData = new FormData();
    formData.append('message', message);
    formData.append('file', imageFile);
    
    // 如果有会话ID，添加到URL参数
    let url = `${API_BASE_URL}/chat/multimodal`;
    if (conversationId) {
      url += `?conversation_id=${conversationId}`;
    }
    
    console.log(`发送多模态请求到: ${url}`);
    
    // 发送请求
    const response = await axios.post(url, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      }
    });
    
    console.log('多模态响应:', response.data);
    
    return {
      content: response.data.response,
      conversationId: response.data.conversation_id
    };
  } catch (error) {
    console.error(`发送多模态消息失败:`, error);
    throw error;
  }
}

// 使用JSON发送多模态消息（Base64图片+文本）
export async function sendMultiModalJsonMessage(
  message: string,
  imageData: string,
  conversationId?: string,
  chatHistory?: any[]
) {
  try {
    console.log(`发送多模态JSON消息: '${message}', 图片数据长度: ${imageData.length}, conversationId: ${conversationId || '新会话'}, 历史消息数: ${chatHistory?.length || 0}`);
    
    // 确保图片 base64 数据格式正确
    let processedImageData = imageData;
    if (imageData.startsWith('data:')) {
      // 已经是正确格式，保持不变
      console.log('图片数据已包含 data URI 前缀');
    } else {
      // 添加 data URI 前缀
      processedImageData = `data:image/jpeg;base64,${imageData}`;
      console.log('已添加 data URI 前缀到图片数据');
    }
    
    // 确保聊天历史中每个消息对象都有role和content字段
    const sanitizedChatHistory = chatHistory ? chatHistory.map(msg => {
      // 确保消息有必要的字段
      if (typeof msg === 'object' && msg !== null) {
        return {
          role: msg.role || 'user',
          content: msg.content || '',
          timestamp: msg.timestamp || new Date().toISOString()
        };
      }
      // 跳过无效消息
      console.warn('跳过无效历史消息', msg);
      return null;
    }).filter(Boolean) : [];
    
    // 构建请求对象
    const request: MultiModalChatRequest = {
      message,
      chat_history: sanitizedChatHistory,
      image_data: processedImageData
    };
    
    // 如果有会话ID，添加到URL参数
    let url = `${API_BASE_URL}/chat/multimodal-json`;
    if (conversationId) {
      url += `?conversation_id=${conversationId}`;
    }
    
    console.log(`发送多模态JSON请求到: ${url}`);
    console.log(`请求历史消息数: ${sanitizedChatHistory.length}`);
    
    // 发送请求
    const response = await axios.post(url, request, {
      headers: {
        'Content-Type': 'application/json',
      }
    });
    
    console.log('多模态JSON响应:', response.data);
    
    // 确保响应内容是字符串
    let content = '';
    if (response.data && response.data.response) {
      if (typeof response.data.response === 'string') {
        content = response.data.response;
      } else {
        // 如果响应不是字符串，尝试转换
        try {
          content = JSON.stringify(response.data.response);
        } catch (err) {
          console.error('响应内容转换失败:', err);
          content = '收到响应，但格式无法处理。';
        }
      }
    } else {
      content = '未收到有效响应。';
    }
    
    return {
      content: content,
      conversationId: response.data.conversation_id || conversationId
    };
  } catch (error) {
    console.error(`发送多模态JSON消息失败:`, error);
    throw error;
  }
}

// 发送流式消息
export async function sendStreamMessage(
  message: string, 
  conversationId?: string,
  chatHistory?: any[],
  onTokenReceived?: (token: string) => void
): Promise<{ content: string, conversationId: string }> {
  return new Promise((resolve, reject) => {
    try {
      console.log(`发送流式消息: '${message}', conversationId: ${conversationId || '新会话'}, 历史消息数: ${chatHistory?.length || 0}`);
      
      // 记录收到的内容
      let receivedContent = '';
      let receivedConversationId = conversationId || '';
      
      // 构建请求URL，包含消息和会话ID
      const params = new URLSearchParams();
      if (conversationId) {
        params.append('conversation_id', conversationId);
      }
      
      // 使用axios发送包含消息内容和聊天历史的POST请求
      const request: ChatRequest = {
        message,
        chat_history: chatHistory || []
      };
      
      console.log('准备发送流式请求，数据:', JSON.stringify(request, null, 2));
      
      // 先发送POST请求包含完整数据
      axios.post(`${API_BASE_URL}/chat/stream`, request, {
        params: conversationId ? { conversation_id: conversationId } : {},
        headers: { 'Content-Type': 'application/json' }
      }).catch(error => {
        console.error('初始请求发送失败:', error);
        // 继续处理，因为我们主要关注EventSource连接
      });
      
      // 构建事件源URL，使用相同的会话ID
      let eventSourceUrl = `${API_BASE_URL}/chat/stream`;
      if (conversationId) {
        eventSourceUrl += `?conversation_id=${conversationId}`;
      }
      
      console.log(`建立EventSource连接: ${eventSourceUrl}`);
      
      // 创建EventSource用于接收流式响应
      const eventSource = new EventSource(eventSourceUrl);
      
      // 处理接收到的消息
      eventSource.onmessage = (event: MessageEvent) => {
        try {
          console.log('收到消息事件:', event.data);
          
          // 字符串数据直接作为token
          const token = event.data;
          receivedContent += token;
          
          // 调用回调函数更新UI
          if (onTokenReceived) {
            onTokenReceived(token);
          }
        } catch (error) {
          console.error('处理消息事件失败:', error);
        }
      };
      
      // 处理完成事件
      eventSource.addEventListener('done', (event: Event) => {
        try {
          const messageEvent = event as MessageEvent;
          console.log('收到完成事件:', messageEvent.data);
          
          // 尝试解析数据
          let data;
          try {
            data = JSON.parse(messageEvent.data);
          } catch (parseError) {
            console.log('完成事件JSON解析失败，使用空对象');
            data = {};
          }
          
          if (data && data.conversation_id) {
            receivedConversationId = data.conversation_id;
          }
          
          console.log(`流式响应完成，会话ID: ${receivedConversationId}, 内容长度: ${receivedContent.length}`);
          
          // 关闭事件源
          eventSource.close();
          
          // 返回结果
          resolve({
            content: receivedContent,
            conversationId: receivedConversationId
          });
        } catch (error) {
          console.error('处理完成事件失败:', error);
          eventSource.close();
          reject(error);
        }
      });
      
      // 处理错误事件
      eventSource.addEventListener('error', (event: Event) => {
        console.error('EventSource错误:', event);
        eventSource.close();
        reject(new Error('流式响应连接出错'));
      });
      
    } catch (error) {
      console.error('初始化流式请求失败:', error);
      reject(error);
    }
  });
}

// 获取对话历史
export const getChatHistory = async (conversationId: string) => {
  const response = await axios.get(`${API_BASE_URL}/history/${conversationId}`);
  return response.data;
}; 