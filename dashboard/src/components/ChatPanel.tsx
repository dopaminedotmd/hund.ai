import { useState, useRef, useEffect } from 'react';
import type { FormEvent } from 'react';
import { StreamingText } from './common/StreamingText';

interface ChatPanelProps {
  connectionStatus: 'online' | 'offline';
  activeRunId: string | null;
  onSendMessageExternal?: (msg: string) => void;
}

interface Message {
  id: string;
  sender: 'user' | 'hund' | 'system' | 'levelup';
  text: string;
  timestamp: string;
  isStreaming?: boolean;
}

export function ChatPanel({ connectionStatus, activeRunId, onSendMessageExternal }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([
    { id: '1', sender: 'hund', text: 'hund ser dig. hund är ansluten och redo att bistå.', timestamp: new Date().toLocaleTimeString() }
  ]);
  const [inputVal, setInputVal] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Exponera sändning till externa komponenter (som QuickActions widget)
  useEffect(() => {
    if (onSendMessageExternal) {
      // Vi sätter en global handler så att widgets kan skicka till chatten
      (window as any).sendToHundChat = (text: string) => {
        handleSendMessage(text);
      };
    }
    return () => {
      delete (window as any).sendToHundChat;
    };
  }, [onSendMessageExternal]);

  const handleSendMessage = (text: string) => {
    if (!text.trim()) return;

    const userMsg: Message = {
      id: Math.random().toString(),
      sender: 'user',
      text: text,
      timestamp: new Date().toLocaleTimeString()
    };

    setMessages(prev => [...prev, userMsg]);

    const fetchChatResponse = async () => {
      // Förbered en tom ström för assistenten
      const assistantMsgId = Math.random().toString();
      
      try {
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text })
        });
        
        if (!res.ok) throw new Error("Backend not responding");
        const data = await res.json();
        
        if (data.status === 'ok') {
          setMessages(prev => [...prev, {
            id: assistantMsgId,
            sender: 'hund',
            text: data.response,
            timestamp: new Date().toLocaleTimeString(),
            isStreaming: true
          }]);
          
          const hasBlocked = data.tool_logs && data.tool_logs.some((log: string) => log.toLowerCase().includes('blocked') || log.toLowerCase().includes('declined'));
          if (hasBlocked) {
            setTimeout(() => {
              setMessages(prev => [...prev, {
                id: Math.random().toString(),
                sender: 'system',
                text: 'Händelse: tool_call_blocked (write operation denied in read-only phase)',
                timestamp: new Date().toLocaleTimeString()
              }]);
            }, 1000);
          }
        } else {
          throw new Error(data.reason || "Unknown error");
        }
      } catch (err) {
        console.warn("Backend chat error, falling back to local processing:", err);
        
        // Lokal parsning av kommandon (/commands) eller mock
        let responseText = '';
        let showSystemBlock = false;
        let isLevelUp = false;

        const cmd = text.trim().toLowerCase();
        if (cmd === '/stats') {
          responseText = 'hund ser: klarhet 98%, precision 99.2%, effektivitet 94%. hund presterar optimalt på main-branch.';
        } else if (cmd === '/skills') {
          responseText = 'hund ser: 3 färdigheter aktiva. shopify-theme är nivå 5. forge-pipelinen har ytterligare 3 i kö.';
        } else if (cmd === '/help') {
          responseText = 'hund ser: tillgängliga kommandon i terminalen är: /stats, /skills, /tools, /help, /progress.';
        } else if (cmd === '/progress') {
          responseText = 'hund ser: 502 tester passerade. framsteg under vecka 26 uppgår till +12% precision och 2 kunskapsenheter.';
        } else if (cmd === '/tools') {
          responseText = 'hund ser: 14 verktyg laddade i dispatch. safety.py övervakar och blockerar otillåtna modifieringar.';
        } else if (cmd.includes('skriv') || cmd.includes('skapa') || cmd.includes('ta bort') || cmd.includes('delete') || cmd.includes('write')) {
          responseText = 'hund ser: skrivåtgärd upptäckt. permission engine nekar skrivrättigheter i denna fas.';
          showSystemBlock = true;
        } else if (cmd.includes('lvl') || cmd.includes('level') || cmd.includes('xp')) {
          responseText = 'hund meddelar: nivå 5 uppnådd. 456 XP registrerat i bas-stats.';
          isLevelUp = true;
        } else {
          responseText = `hund ser: meddelande mottaget "${text}". hund bearbetar kontexten och lagrar trace-information.`;
        }

        setMessages(prev => [...prev, {
          id: assistantMsgId,
          sender: isLevelUp ? 'levelup' : 'hund',
          text: responseText,
          timestamp: new Date().toLocaleTimeString(),
          isStreaming: true
        }]);

        if (showSystemBlock) {
          setTimeout(() => {
            setMessages(prev => [...prev, {
              id: Math.random().toString(),
              sender: 'system',
              text: 'Händelse: tool_call_blocked (write operation denied in read-only phase)',
              timestamp: new Date().toLocaleTimeString()
            }]);
          }, 1200);
        }
      }
    };

    fetchChatResponse();
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!inputVal.trim()) return;
    handleSendMessage(inputVal);
    setInputVal('');
  };

  const handleQuickAction = (cmd: string) => {
    handleSendMessage(cmd);
  };

  const handleStreamComplete = (msgId: string) => {
    setMessages(prev => prev.map(m => m.id === msgId ? { ...m, isStreaming: false } : m));
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', backgroundColor: 'var(--bg-terminal)' }}>
      
      {/* Header (Terminal style) */}
      <div style={{ 
        padding: '16px 24px', 
        borderBottom: '1px solid rgba(255, 255, 255, 0.05)', 
        display: 'flex', 
        justifyContent: 'space-between',
        alignItems: 'center',
        backgroundColor: 'rgba(0, 0, 0, 0.2)'
      }}>
        <div>
          <h3 style={{ 
            fontSize: '14px', 
            fontWeight: 700, 
            fontFamily: 'var(--font-mono)', 
            color: 'var(--text-chat)',
            textTransform: 'uppercase',
            letterSpacing: '0.05em'
          }}>
            Hund terminal
          </h3>
          <p style={{ 
            fontSize: '11px', 
            color: 'var(--text-secondary)', 
            fontFamily: 'var(--font-mono)',
            marginTop: '2px'
          }}>
            Körning: {activeRunId ? activeRunId.substring(0, 16) : 'Lokal interaktion'}
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className={`pulse-dot ${connectionStatus === 'online' ? 'online' : ''}`} style={{
            backgroundColor: connectionStatus === 'online' ? 'var(--status-success)' : 'var(--status-danger)',
            width: '6px',
            height: '6px'
          }} />
          <span style={{ fontSize: '11px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
            {connectionStatus === 'online' ? 'DEV_LINK_ON' : 'DEV_LINK_OFF'}
          </span>
        </div>
      </div>

      {/* Messages View */}
      <div 
        style={{ 
          flex: 1, 
          padding: '24px', 
          overflowY: 'auto', 
          display: 'flex', 
          flexDirection: 'column', 
          gap: '16px',
          fontFamily: 'var(--font-mono)'
        }}
        className="dark-scrollbar"
      >
        {messages.map((m) => {
          if (m.sender === 'system') {
            return (
              <div 
                key={m.id} 
                style={{ 
                  alignSelf: 'center', 
                  backgroundColor: 'rgba(239, 68, 68, 0.08)', 
                  border: '1px solid rgba(239, 68, 68, 0.2)', 
                  color: 'var(--status-danger)', 
                  padding: '8px 16px', 
                  borderRadius: '6px',
                  fontSize: '12px',
                  lineHeight: '1.4',
                  maxWidth: '90%'
                }}
              >
                {m.text}
              </div>
            );
          }

          if (m.sender === 'levelup') {
            return (
              <div 
                key={m.id} 
                style={{ 
                  alignSelf: 'center', 
                  backgroundColor: 'rgba(242, 201, 76, 0.08)', 
                  border: '1px solid rgba(242, 201, 76, 0.2)', 
                  color: 'var(--accent-chalk)', 
                  padding: '12px 20px', 
                  borderRadius: '6px',
                  fontSize: '13px',
                  lineHeight: '1.4',
                  maxWidth: '90%',
                  textAlign: 'center',
                  fontWeight: 600
                }}
              >
                {m.text}
              </div>
            );
          }

          const isUser = m.sender === 'user';
          return (
            <div 
              key={m.id} 
              style={{ 
                alignSelf: isUser ? 'flex-end' : 'flex-start',
                maxWidth: '85%',
                display: 'flex',
                flexDirection: 'column',
                gap: '4px'
              }}
            >
              {/* Sender label */}
              <span style={{ 
                fontSize: '10px', 
                color: isUser ? '#10B981' : 'var(--text-secondary)',
                alignSelf: isUser ? 'flex-end' : 'flex-start',
                textTransform: 'uppercase',
                letterSpacing: '0.05em'
              }}>
                {isUser ? 'William' : 'Hund'}
              </span>

              {/* Message Box */}
              <div style={{ 
                backgroundColor: isUser ? '#1E293B' : 'rgba(255, 255, 255, 0.02)',
                padding: '12px 18px',
                borderRadius: '12px',
                border: isUser ? '1px solid #334155' : '1px solid rgba(255, 255, 255, 0.05)',
                color: isUser ? 'var(--text-on-dark)' : 'var(--text-chat)'
              }}>
                <p style={{ fontSize: '15px', lineHeight: '1.5', whiteSpace: 'pre-wrap', margin: 0 }}>
                  {m.isStreaming ? (
                    <StreamingText 
                      text={m.text} 
                      speed={25} 
                      onComplete={() => handleStreamComplete(m.id)} 
                    />
                  ) : (
                    m.text
                  )}
                </p>
              </div>

              {/* Timestamp */}
              <span style={{ 
                fontSize: '9px', 
                color: 'rgba(255, 255, 255, 0.25)', 
                textAlign: isUser ? 'right' : 'left'
              }}>
                {m.timestamp}
              </span>
            </div>
          );
        })}
        <div ref={messagesEndRef} />
      </div>

      {/* Input panel */}
      <div style={{ 
        padding: '20px 24px', 
        borderTop: '1px solid rgba(255, 255, 255, 0.05)', 
        display: 'flex', 
        flexDirection: 'column', 
        gap: '12px',
        backgroundColor: 'rgba(0, 0, 0, 0.1)'
      }}>
        
        {/* Quick action commands */}
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          {['/stats', '/skills', '/tools', '/help', '/progress'].map(cmd => (
            <button
              key={cmd}
              onClick={() => handleQuickAction(cmd)}
              className="quick-action-pill-terminal"
            >
              {cmd}
            </button>
          ))}
        </div>

        {/* Action input pill form */}
        <form onSubmit={handleSubmit} className="input-action-pill-container">
          <input 
            type="text" 
            value={inputVal}
            onChange={(e) => setInputVal(e.target.value)}
            placeholder="Skriv till hund..." 
            className="input-action-pill-field"
          />
          <button 
            type="submit" 
            disabled={!inputVal.trim()}
            className="input-action-pill-send"
          >
            ↗
          </button>
        </form>

      </div>

      <style>{`
        .quick-action-pill-terminal {
          background-color: rgba(255, 255, 255, 0.05);
          color: var(--text-chat);
          padding: 4px 10px;
          border-radius: var(--radius-pill);
          font-size: 11px;
          font-family: var(--font-mono);
          border: 1px solid rgba(255, 255, 255, 0.05);
          cursor: pointer;
          transition: all 150ms ease;
        }

        .quick-action-pill-terminal:hover {
          background-color: var(--element-active);
          color: #FFFFFF;
          border-color: transparent;
        }

        .input-action-pill-container {
          display: flex;
          align-items: center;
          gap: 8px;
          background-color: #1E293B;
          border: 1px solid #334155;
          border-radius: var(--radius-pill);
          padding: 4px;
          width: 100%;
        }

        .input-action-pill-field {
          flex: 1;
          background: none;
          border: none;
          outline: none;
          color: var(--text-chat);
          font-family: var(--font-mono);
          font-size: 14px;
          padding: 8px 16px;
        }

        .input-action-pill-field::placeholder {
          color: #64748B;
        }

        .input-action-pill-send {
          width: 32px;
          height: 32px;
          border-radius: 50%;
          background-color: var(--element-active);
          color: white;
          display: flex;
          align-items: center;
          justify-content: center;
          border: none;
          font-size: 13px;
          cursor: pointer;
          transition: background 200ms ease, transform 200ms ease;
        }

        .input-action-pill-send:hover:not(:disabled) {
          background-color: #000000;
          transform: rotate(45deg);
        }

        .input-action-pill-send:disabled {
          opacity: 0.3;
          cursor: not-allowed;
        }
      `}</style>
    </div>
  );
}
