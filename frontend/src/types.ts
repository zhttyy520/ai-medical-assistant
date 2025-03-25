// 聊天消息类型
export interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp?: string;
}

// API请求类型
export interface ChatRequest {
  message: string;
  chat_history?: Message[];
}

// API响应类型
export interface ChatResponse {
  response: string;
  conversation_id: string;
}

// 聊天状态类型
export interface ChatState {
  messages: Message[];
  loading: boolean;
  error: string | null;
  conversationId: string | null;
} 