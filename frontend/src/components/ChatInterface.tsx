import React, { useState, useEffect, useRef } from 'react';
import { sendMessage, Message, getChatHistory, sendMultiModalJsonMessage } from '../services/chatService';
import ReactMarkdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';
import remarkGfm from 'remark-gfm';
import './ChatInterface.css';

interface ChatInterfaceProps {
  // 可以在这里添加props
}

// 定义响应类型
interface ChatResponse {
  content: string;
  conversationId: string;
}

const ChatInterface: React.FC<ChatInterfaceProps> = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | undefined>(undefined);
  const [useStreamResponse, setUseStreamResponse] = useState<boolean>(true);
  const [currentStreamContent, setCurrentStreamContent] = useState<string>('');
  const [selectedImage, setSelectedImage] = useState<File | null>(null);
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const cleanupRef = useRef<(() => void) | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

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
        content: '您好！我是AI医疗助手，可以为您解答医疗健康方面的基本问题。您现在可以**发送文字或图片**进行咨询。请注意：我提供的信息仅供参考，不构成医疗建议，如有紧急情况请立即就医。',
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

  // 处理图片选择
  const handleImageSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files;
    if (files && files.length > 0) {
      const file = files[0];
      
      // 检查文件大小（限制为5MB）
      if (file.size > 5 * 1024 * 1024) {
        alert('图片大小不能超过5MB');
        return;
      }
      
      // 检查文件类型
      if (!file.type.startsWith('image/')) {
        alert('请选择图片文件');
        return;
      }
      
      console.log(`选择了图片: ${file.name}, 大小: ${(file.size / 1024).toFixed(2)}KB, 类型: ${file.type}`);
      
      // 设置选中的图片文件
      setSelectedImage(file);
      
      // 创建预览URL
      const previewUrl = URL.createObjectURL(file);
      setPreviewImage(previewUrl);
      
      // 在组件卸载时释放预览URL
      return () => URL.revokeObjectURL(previewUrl);
    }
  };

  // 清除选中的图片
  const clearSelectedImage = () => {
    setSelectedImage(null);
    setPreviewImage(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  // 触发图片选择对话框
  const triggerImageUpload = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  // 将图片转换为Base64
  const convertImageToBase64 = (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = error => reject(error);
      reader.readAsDataURL(file);
    });
  };

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
          timestamp: msg.timestamp,
          image_url: msg.image_url
        }));
        
        setMessages(formattedMessages);
        console.log(`加载了 ${formattedMessages.length} 条历史消息`);
      } else {
        // 如果没有历史消息，显示欢迎消息
        const welcomeMessage: Message = {
          role: 'assistant',
          content: '欢迎回来！我是AI医疗助手，请问有什么可以继续帮您？您可以发送文字或图片进行咨询。',
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
    // 如果正在加载或者消息为空，不处理
    if (isLoading || !input.trim()) return;
    
    // 清除消息输入框并设置加载状态
    const messageContent = input.trim();
    setInput('');
    setIsLoading(true);
    
    try {
      console.log('发送新消息:', messageContent);
      
      // 准备聊天历史 - 仅包含文本消息，不包含系统消息和临时消息
      const chatHistory = messages
        .filter(msg => msg.role !== 'system' && !msg.isTemporary)
        .map(msg => ({
          role: msg.role,
          content: msg.content,
          timestamp: msg.timestamp,
          ...(msg.image_url ? { image_url: msg.image_url } : {})
        }));
      
      console.log(`准备聊天历史, 共 ${chatHistory.length} 条消息`);
      
      // 在消息列表中添加用户消息
      const userMessage: Message = {
        role: 'user',
        content: messageContent,
        timestamp: new Date().toISOString(),
        ...(selectedImage ? { image_url: URL.createObjectURL(selectedImage) } : {})
      };
      
      setMessages(currentMessages => [...currentMessages, userMessage]);
      
      // 清除图片选择
      const imageWasSent = !!selectedImage;
      if (selectedImage) {
        setPreviewImage('');
        setSelectedImage(null);
      }
      
      // 添加一个临时的助手消息占位符
      const assistantMessage: Message = {
        role: 'assistant',
        content: '',
        timestamp: new Date().toISOString(),
        isTemporary: true
      };
      
      setMessages(currentMessages => [...currentMessages, assistantMessage]);
      
      // 记录助手消息的索引，以便后续更新
      const assistantMessageIndex = messages.length + 1;  // +1是因为前面刚添加了用户消息
      
      // 初始化响应变量
      let response: { content: string, conversationId: string };
      
      // 重置流式内容
      setCurrentStreamContent('');
      
      // 根据是否有图片选择不同的API
      if (imageWasSent) {
        // 如果有图片，使用多模态API
        console.log('使用多模态API发送图片和文本');
        
        // 转换图片为Base64
        const imageBase64 = await convertImageToBase64(selectedImage);
        
        // 准备发送给后端的历史记录 - 不包括当前发送的用户消息
        const historyToSend = messages
          .filter(msg => !msg.isTemporary && msg.role !== 'system')
          .map(msg => ({
            role: msg.role,
            content: msg.content,
            timestamp: msg.timestamp
          }));
        
        console.log(`为多模态请求准备的历史消息: ${historyToSend.length}条`);
        
        // 使用JSON版本的多模态API（Base64）
        response = await sendMultiModalJsonMessage(
          messageContent,
          imageBase64,
          conversationId,
          historyToSend
        );
        
        // 更新助手消息
        setMessages(currentMessages => {
          if (assistantMessageIndex >= 0 && assistantMessageIndex < currentMessages.length) {
            const updatedMessages = [...currentMessages];
            updatedMessages[assistantMessageIndex] = {
              ...updatedMessages[assistantMessageIndex],
              content: response.content,
              isTemporary: false
            };
            return updatedMessages;
          }
          return currentMessages;
        });
      } else {
        // 没有图片，使用普通文本API
        // 处理流式响应
        if (useStreamResponse) {
          response = await sendMessage(
            messageContent, 
            conversationId, 
            // 确保发送的是最新的聊天历史，不包括刚添加的用户消息和临时助手消息
            messages.filter(msg => !msg.isTemporary).map(msg => ({
              role: msg.role,
              content: msg.content,
              timestamp: msg.timestamp
            })),
            useStreamResponse,
            // 添加token接收回调，用于实时更新UI
            (token: string) => {
              // 更新当前流式内容
              setCurrentStreamContent(prev => {
                const newContent = prev + token;
                
                // 更新消息列表中的助手回复
                setMessages(currentMessages => {
                  if (assistantMessageIndex >= 0 && assistantMessageIndex < currentMessages.length) {
                    const updatedMessages = [...currentMessages];
                    updatedMessages[assistantMessageIndex] = {
                      ...updatedMessages[assistantMessageIndex],
                      content: newContent,
                      isTemporary: false
                    };
                    return updatedMessages;
                  }
                  return currentMessages;
                });
                
                return newContent;
              });
            }
          );
        } else {
          // 非流式响应
          response = await sendMessage(
            messageContent, 
            conversationId, 
            // 确保发送的是最新的聊天历史，不包括刚添加的用户消息和临时助手消息
            messages.filter(msg => !msg.isTemporary).map(msg => ({
              role: msg.role,
              content: msg.content,
              timestamp: msg.timestamp
            }))
          );
          
          // 更新助手消息
          setMessages(currentMessages => {
            if (assistantMessageIndex >= 0 && assistantMessageIndex < currentMessages.length) {
              const updatedMessages = [...currentMessages];
              updatedMessages[assistantMessageIndex] = {
                ...updatedMessages[assistantMessageIndex],
                content: response.content,
                isTemporary: false
              };
              return updatedMessages;
            }
            return currentMessages;
          });
        }
      }
      
      console.log('收到回复:', response);
      
      // 如果是新会话，保存会话ID
      if (response.conversationId && (!conversationId || conversationId !== response.conversationId)) {
        setConversationId(response.conversationId);
        console.log(`设置会话ID: ${response.conversationId}`);
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
  const MarkdownContent = ({ content }: { content: string | any }) => {
    // 确保内容是字符串类型
    const safeContent = React.useMemo(() => {
      if (typeof content === 'string') {
        return content;
      } else if (content === null || content === undefined) {
        return '';
      } else if (Array.isArray(content)) {
        // 如果是数组，尝试找到文本内容并连接
        return content
          .map(item => {
            if (typeof item === 'string') return item;
            if (item && typeof item === 'object' && 'text' in item) return item.text;
            return JSON.stringify(item);
          })
          .join('\n');
      } else if (typeof content === 'object') {
        // 如果是对象，尝试提取文本内容或转为JSON字符串
        if ('text' in content) return String(content.text);
        if ('content' in content) return String(content.content);
        return JSON.stringify(content);
      }
      // 其他类型尝试转换为字符串
      return String(content);
    }, [content]);

    return (
      <div className="markdown-content">
        <ReactMarkdown 
          rehypePlugins={[rehypeSanitize]} 
          remarkPlugins={[remarkGfm]}
        >
          {safeContent}
        </ReactMarkdown>
      </div>
    );
  };

  return (
    <div className="chat-container">
      <div className="header">
        <div className="title">AI医疗助手</div>
        <div className="actions">
          <div className="stream-toggle">
            {/* <label className="toggle-label">
              <input 
                type="checkbox" 
                checked={useStreamResponse}
                onChange={(e) => setUseStreamResponse(e.target.checked)}
                disabled={isLoading}
              />
              <span>流式响应</span>
            </label> */}
          </div>
        </div>
      </div>
      
      <div className="messages-container">
        {/* 显示之前的消息 */}
        {messages.map((message, index) => (
          <div key={index} className={`message ${message.role}`}>
            <div className="message-bubble">
              {/* 如果消息中包含图片，显示图片 */}
              {message.image_url && (
                <div className="message-image-container">
                  <img 
                    src={message.image_url} 
                    alt="用户上传的图片" 
                    className="message-image"
                    onClick={() => window.open(message.image_url, '_blank')}
                  />
                </div>
              )}
              
              {/* 显示消息内容 */}
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
            <div className="message-info">
              AI医疗助手 · 正在思考...
            </div>
          </div>
        )}
        
        {/* 用于自动滚动的引用元素 */}
        <div ref={messagesEndRef} />
      </div>
      
      {/* 图片预览区域 */}
      {previewImage && (
        <div className="image-preview-container">
          <img src={previewImage} alt="预览" className="image-preview" />
          <button 
            className="clear-image-button"
            onClick={clearSelectedImage}
          >
            ×
          </button>
        </div>
      )}
      
      {/* 确保输入框始终可见 */}
      <div className="input-container">
        {/* 隐藏的文件输入 */}
        <input
          type="file"
          accept="image/*"
          onChange={handleImageSelect}
          style={{ display: 'none' }}
          ref={fileInputRef}
        />
        
        {/* 图片上传按钮 */}
        <button 
          className="image-upload-button"
          onClick={triggerImageUpload}
          disabled={isLoading}
          style={{width:'80px'}}
        >
          图片
        </button>
        
        {/* 文本输入框 */}
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSendMessage()}
          placeholder="请输入您的健康问题..."
          disabled={isLoading}
          className={selectedImage ? "with-image" : ""}
        />
        
        {/* 发送按钮 */}
        <button 
          className="send-button"
          onClick={handleSendMessage} 
          disabled={isLoading || (!input.trim() && !selectedImage)}
        >
          {isLoading ? '发送中...' : '发送'}
        </button>
      </div>
    </div>
  );
};

export default ChatInterface; 