import { useState, useRef, useEffect } from 'react';
import type { FormEvent } from 'react';

interface ChatPanelProps {
  connectionStatus: 'online' | 'offline';
  activeRunId: string | null;
}

interface Message {
  id: string;
  sender: 'user' | 'hund' | 'system';
  text: string;
  timestamp: string;
}

export function ChatPanel({ connectionStatus, activeRunId }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([
    { id: '1', sender: 'hund', text: 'Välkommen till Hund.ai. Jag är uppkopplad och redo.', timestamp: new Date().toLocaleTimeString() }
  ]);
  const [inputVal, setInputVal] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!inputVal.trim()) return;

    const userMsg: Message = {
      id: Math.random().toString(),
      sender: 'user',
      text: inputVal,
      timestamp: new Date().toLocaleTimeString()
    };

    setMessages(prev => [...prev, userMsg]);
    setInputVal('');

    // Phase 5 Read-Only Warning Mock Reply
    setTimeout(() => {
      const responseText = inputVal.toLowerCase().includes('skriv') || inputVal.toLowerCase().includes('skapa')
        ? 'Jag upptäckte en skrivåtgärd. Eftersom Phase 5 körs i read-only läge blockeras detta kommando av min lokala PermissionEngine.'
        : `Jag mottog ditt meddelande: "${inputVal}". Traces registreras live i Ops-panelen.`;
      
      setMessages(prev => [...prev, {
        id: Math.random().toString(),
        sender: 'hund',
        text: responseText,
        timestamp: new Date().toLocaleTimeString()
      }]);

      if (inputVal.toLowerCase().includes('skriv') || inputVal.toLowerCase().includes('skapa')) {
        setMessages(prev => [...prev, {
          id: Math.random().toString(),
          sender: 'system',
          text: 'Händelse: tool_call_blocked (write operation denied in read-only phase)',
          timestamp: new Date().toLocaleTimeString()
        }]);
      }
    }, 1000);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', backgroundColor: 'var(--bg-secondary)' }}>
      {/* Header */}
      <div style={{ 
        padding: '16px', 
        borderBottom: '1px solid var(--border-color)', 
        display: 'flex', 
        justifyContent: 'space-between',
        alignItems: 'center'
      }}>
        <div>
          <h2 style={{ fontSize: '1.1rem', fontWeight: 600 }}>Hund Session</h2>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            Run: {activeRunId || 'Ingen aktiv körning'}
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ 
            width: '8px', 
            height: '8px', 
            borderRadius: '50%', 
            backgroundColor: connectionStatus === 'online' ? 'var(--status-success)' : 'var(--status-danger)' 
          }} />
          <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            {connectionStatus === 'online' ? 'Connector Online' : 'Connector Offline'}
          </span>
        </div>
      </div>

      {/* Messages */}
      <div style={{ flex: 1, padding: '16px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {messages.map((m) => {
          if (m.sender === 'system') {
            return (
              <div key={m.id} style={{ 
                alignSelf: 'center', 
                backgroundColor: 'rgba(239, 68, 68, 0.1)', 
                border: '1px solid var(--status-danger)', 
                color: 'var(--status-danger)', 
                padding: '8px 12px', 
                borderRadius: '4px',
                fontSize: '0.8rem',
                fontFamily: 'var(--font-mono)'
              }}>
                {m.text}
              </div>
            );
          }
          const isUser = m.sender === 'user';
          return (
            <div key={m.id} style={{ 
              alignSelf: isUser ? 'flex-end' : 'flex-start',
              maxWidth: '80%',
              backgroundColor: isUser ? '#1e293b' : 'var(--bg-primary)',
              padding: '12px 16px',
              borderRadius: '8px',
              border: '1px solid var(--border-color)'
            }}>
              <p style={{ fontSize: '0.9rem', lineHeight: '1.4' }}>{m.text}</p>
              <span style={{ display: 'block', fontSize: '0.7rem', color: 'var(--text-muted)', textAlign: 'right', marginTop: '4px' }}>
                {m.timestamp}
              </span>
            </div>
          );
        })}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} style={{ padding: '16px', borderTop: '1px solid var(--border-color)', display: 'flex', gap: '8px' }}>
        <input 
          type="text" 
          value={inputVal}
          onChange={(e) => setInputVal(e.target.value)}
          placeholder="Fråga Hund eller testa skrivkommando..." 
          style={{ 
            flex: 1, 
            padding: '12px', 
            borderRadius: '6px', 
            border: '1px solid var(--border-color)', 
            backgroundColor: 'var(--bg-primary)',
            color: 'var(--text-primary)',
            outline: 'none'
          }}
        />
        <button type="submit" style={{ 
          padding: '0 20px', 
          borderRadius: '6px', 
          backgroundColor: 'var(--status-info)', 
          border: 'none', 
          color: 'white', 
          fontWeight: 'bold',
          cursor: 'pointer' 
        }}>
          Sänd
        </button>
      </form>
    </div>
  );
}
