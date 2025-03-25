import { createSlice, createAsyncThunk, PayloadAction } from '@reduxjs/toolkit';
import axios from 'axios';
import { ChatState, Message, ChatRequest, ChatResponse } from '../types';

// API基础URL
const API_BASE_URL = 'http://localhost:8000/api';

// 初始状态
const initialState: ChatState = {
  messages: [],
  loading: false,
  error: null,
  conversationId: null,
};

// 发送消息的异步Action
export const sendMessage = createAsyncThunk(
  'chat/sendMessage',
  async (message: string, { getState, rejectWithValue }) => {
    try {
      const state = getState() as { chat: ChatState };
      const { messages, conversationId } = state.chat;
      
      const request: ChatRequest = {
        message,
        chat_history: messages,
      };
      
      const headers: Record<string, string> = {};
      if (conversationId) {
        headers['X-Conversation-ID'] = conversationId;
      }
      
      const response = await axios.post<ChatResponse>(
        `${API_BASE_URL}/chat`,
        request,
        { headers }
      );
      
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response) {
        return rejectWithValue(error.response.data);
      }
      return rejectWithValue('发送消息失败');
    }
  }
);

// 获取对话历史的异步Action
export const fetchHistory = createAsyncThunk(
  'chat/fetchHistory',
  async (conversationId: string, { rejectWithValue }) => {
    try {
      const response = await axios.get(
        `${API_BASE_URL}/history/${conversationId}`
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response) {
        return rejectWithValue(error.response.data);
      }
      return rejectWithValue('获取历史记录失败');
    }
  }
);

// Chat Slice
const chatSlice = createSlice({
  name: 'chat',
  initialState,
  reducers: {
    addMessage(state, action: PayloadAction<Message>) {
      state.messages.push(action.payload);
    },
    setLoading(state, action: PayloadAction<boolean>) {
      state.loading = action.payload;
    },
    setError(state, action: PayloadAction<string | null>) {
      state.error = action.payload;
    },
    setConversationId(state, action: PayloadAction<string>) {
      state.conversationId = action.payload;
    },
    clearChat(state) {
      state.messages = [];
      state.error = null;
      state.conversationId = null;
    },
  },
  extraReducers: (builder) => {
    builder
      // 发送消息
      .addCase(sendMessage.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(sendMessage.fulfilled, (state, action) => {
        state.loading = false;
        if (action.payload.conversation_id) {
          state.conversationId = action.payload.conversation_id;
        }
        // 不需要在这里添加消息，因为我们使用流式响应
      })
      .addCase(sendMessage.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload as string || '发送消息失败';
      })
      
      // 获取历史记录
      .addCase(fetchHistory.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchHistory.fulfilled, (state, action) => {
        state.loading = false;
        state.messages = action.payload.history;
        state.conversationId = action.payload.conversation_id;
      })
      .addCase(fetchHistory.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload as string || '获取历史记录失败';
      });
  },
});

export const { addMessage, setLoading, setError, setConversationId, clearChat } = chatSlice.actions;

export default chatSlice.reducer; 