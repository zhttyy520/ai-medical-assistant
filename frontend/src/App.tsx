import React from 'react';
import './App.css';
import ChatInterface from './components/ChatInterface';

function App() {
  return (
    <div className="App">
      <header className="App-header">
        <div className="logo-container">
          <span className="logo-icon">🩺</span>
          <h1>AI医疗助手</h1>
        </div>
        <div className="header-subtitle">
          专业、智能的医疗咨询服务
        </div>
      </header>
      <main>
        <ChatInterface />
      </main>
      <footer className="App-footer">
        <p>© 2025 AI医疗助手 · 仅供参考，非医疗建议</p>
      </footer>
    </div>
  );
}

export default App;
