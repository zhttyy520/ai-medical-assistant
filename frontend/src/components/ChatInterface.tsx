import React, { useState, useEffect, useRef } from 'react';
import { sendMessage, Message, getChatHistory } from '../services/chatService';
import ReactMarkdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';
import remarkGfm from 'remark-gfm';
import './ChatInterface.css';

interface ChatInterfaceProps {
  // 可以在这里添加props
}

const ChatInterface: React.FC<ChatInterfaceProps> = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | undefined>(undefined);
  const [useStreamResponse, setUseStreamResponse] = useState<boolean>(true);
  const [currentStreamContent, setCurrentStreamContent] = useState<string>('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const cleanupRef = useRef<(() => void) | null>(null);

  // 自动滚动到底部
  useEffect(() => {
    // 使用setTimeout确保DOM已更新后再滚动
    setTimeout(() => {
      scrollToBottom();
    }, 0);
  }, [messages]);

  // 第一次加载时检查本地存储的会话ID
  useEffect(() => {
    // 从本地存储中恢复会话ID
    const savedConversationId = localStorage.getItem('medicalAssistantConversationId');
    
    if (savedConversationId) {
      console.log(`从本地存储恢复会话ID: ${savedConversationId}`);
      setConversationId(savedConversationId);
      // 加载历史消息
      loadChatHistory(savedConversationId);
    } else {
      // 添加欢迎消息
      const welcomeMessage: Message = {
        role: 'assistant',
        content: '您好！我是AI医疗助手，可以为您解答医疗健康方面的基本问题。请注意：我提供的信息仅供参考，不构成医疗建议，如有紧急情况请立即就医。请问有什么可以帮您？',
        timestamp: new Date().toISOString()
      };
      
      setMessages([welcomeMessage]);
    }
  }, []);
  
  // 保存会话ID到本地存储
  useEffect(() => {
    if (conversationId) {
      localStorage.setItem('medicalAssistantConversationId', conversationId);
      console.log(`保存会话ID到本地存储: ${conversationId}`);
    }
  }, [conversationId]);

  // 加载历史聊天记录
  const loadChatHistory = async (conversationId: string) => {
    try {
      console.log(`加载会话历史: ${conversationId}`);
      const history = await getChatHistory(conversationId);
      
      if (history && history.history && history.history.length > 0) {
        // 转换历史消息为我们应用的格式
        const formattedMessages: Message[] = history.history.map((msg: any) => ({
          role: msg.role,
          content: msg.content,
          timestamp: msg.timestamp
        }));
        
        setMessages(formattedMessages);
        console.log(`加载了 ${formattedMessages.length} 条历史消息`);
      } else {
        // 如果没有历史消息，显示欢迎消息
        const welcomeMessage: Message = {
          role: 'assistant',
          content: '欢迎回来！我是AI医疗助手，请问有什么可以继续帮您？',
          timestamp: new Date().toISOString()
        };
        
        setMessages([welcomeMessage]);
      }
    } catch (error) {
      console.error('加载历史消息失败:', error);
      // 加载失败时显示错误消息
      const errorMessage: Message = {
        role: 'system',
        content: '加载历史消息失败，但您可以继续新的对话。',
        timestamp: new Date().toISOString()
      };
      
      setMessages([errorMessage]);
    }
  };

  const scrollToBottom = () => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ 
        behavior: 'smooth',
        block: 'end' // 确保滚动到底部
      });
    }
  };

  // 处理发送消息
  const handleSendMessage = async () => {
    if (!input.trim() || isLoading) return;
    
    console.log(`发送消息: "${input}", 使用流式响应: ${useStreamResponse}`);
    setIsLoading(true);
    
    // 重置流式内容
    setCurrentStreamContent('');
    
    // 清除之前的清理函数
    if (cleanupRef.current) {
      console.log('清理上一个流式连接');
      cleanupRef.current();
      cleanupRef.current = null;
    }
    
    // 添加用户消息到聊天列表
    const userMessage: Message = {
      role: 'user',
      content: input,
      timestamp: new Date().toISOString()
    };
    
    // 更新消息列表，使用函数式更新确保获取最新状态
    setMessages(currentMessages => [...currentMessages, userMessage]);
    
    const messageToSend = input.trim();
    setInput('');
    
    try {
      // 准备消息历史 - 获取最新的消息列表
      const chatHistory = messages.concat(userMessage).map(msg => ({
        role: msg.role,
        content: msg.content,
        timestamp: msg.timestamp
      }));
      
      console.log('准备发送请求，参数:', { 
        message: messageToSend, 
        conversationId, 
        chatHistoryLength: chatHistory.length,
        useStreamResponse
      });
      
      // 如果使用流式响应，添加一个空的助手消息用于实时更新
      let assistantMessageIndex = -1;
      if (useStreamResponse) {
        const tempAssistantMessage: Message = {
          role: 'assistant',
          content: '',
          timestamp: new Date().toISOString()
        };
        
        // 使用函数式更新来确保获取最新状态
        setMessages(currentMessages => {
          const updatedMessages = [...currentMessages, tempAssistantMessage];
          assistantMessageIndex = updatedMessages.length - 1; // 新消息的索引
          return updatedMessages;
        });
        
        // 等待状态更新完成
        await new Promise(resolve => setTimeout(resolve, 0));
      }
      
      // 使用消息发送函数，传递聊天历史、流式响应参数和token回调
      const response = await sendMessage(
        messageToSend, 
        conversationId, 
        chatHistory,
        useStreamResponse,
        // 添加token接收回调，用于实时更新UI
        useStreamResponse ? (token: string) => {
          
          // 更新当前流式内容
          setCurrentStreamContent(prev => {
            const newContent = prev + token;
            
            // 更新消息列表中的助手回复
            setMessages(currentMessages => {
              if (assistantMessageIndex >= 0 && assistantMessageIndex < currentMessages.length) {
                const updatedMessages = [...currentMessages];
                updatedMessages[assistantMessageIndex] = {
                  ...updatedMessages[assistantMessageIndex],
                  content: newContent
                };
                return updatedMessages;
              }
              return currentMessages;
            });
            
            return newContent;
          });
        } : undefined
      );
      
      console.log('收到回复:', response);
      
      // 如果是新会话，保存会话ID
      if (response.conversationId && !conversationId) {
        setConversationId(response.conversationId);
        console.log(`设置新会话ID: ${response.conversationId}`);
      }
      
      // 如果不是使用流式响应，添加助手回复到消息列表
      if (!useStreamResponse) {
        const assistantMessage: Message = {
          role: 'assistant',
          content: response.content,
          timestamp: new Date().toISOString()
        };
        
        setMessages(currentMessages => [...currentMessages, assistantMessage]);
      }
      
      setIsLoading(false);
      
    } catch (error: any) {
      console.error('发送消息时出错:', error);
      setIsLoading(false);
      
      // 添加详细的错误消息
      const errorContent = `很抱歉，服务暂时出现问题: ${error.message || '未知错误'}

如果您需要紧急医疗帮助，请立即联系您的医生或拨打急救电话。`;
      
      const errorMessage: Message = {
        role: 'system',
        content: errorContent,
        timestamp: new Date().toISOString()
      };
      
      setMessages(currentMessages => [...currentMessages, errorMessage]);
    }
  };

  // Markdown渲染组件
  const MarkdownContent = ({ content }: { content: string }) => {
    return (
      <div className="markdown-content">
        <ReactMarkdown 
          rehypePlugins={[rehypeSanitize]} 
          remarkPlugins={[remarkGfm]}
        >
          {content}
        </ReactMarkdown>
      </div>
    );
  };

  return (
    <div className="chat-container">
      <div className="header">
        <div className="title">AI医疗助手</div>
        <div className="actions">
          {/* <div className="stream-toggle">
            <label className="toggle-label">
              <input 
                type="checkbox" 
                checked={useStreamResponse}
                onChange={(e) => setUseStreamResponse(e.target.checked)}
                disabled={isLoading}
              />
              <span>使用流式响应</span>
            </label>
          </div> */}
        </div>
      </div>
      
      <div className="messages-container">
        {/* 显示之前的消息 */}
        {messages.map((message, index) => (
          <div key={index} className={`message ${message.role}`}>
            <div className="message-bubble">
              {message.role === 'assistant' ? (
                <MarkdownContent content={message.content} />
              ) : (
                message.content
              )}
            </div>
            <div className="message-info">
              {message.role === 'user' ? '您' : message.role === 'system' ? '系统消息' : 'AI医疗助手'} 
              · 
              {new Date(message.timestamp || '').toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
            </div>
          </div>
        ))}
        
        {/* 显示加载状态 */}
        {isLoading && (
          <div className="message assistant">
            {/* <div className="message-bubble">
              <div className="typing-indicator">
                <span></span>
              </div>
            </div> */}
            <div className="message-info">
              AI医疗助手 · 正在思考...
            </div>
          </div>
        )}
        
        {/* 用于自动滚动的引用元素 */}
        <div ref={messagesEndRef} />
      </div>
      
      {/* 确保输入框始终可见 */}
      <div className="input-container">
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSendMessage()}
          placeholder="请输入您的健康问题..."
          disabled={isLoading}
        />
        <button onClick={handleSendMessage} disabled={isLoading || !input.trim()}>
          {isLoading ? '发送中...' : '发送'}
        </button>
      </div>
    </div>
  );
};

export default ChatInterface; 