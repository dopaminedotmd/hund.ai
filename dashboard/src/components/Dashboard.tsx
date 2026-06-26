import { useState, useEffect } from 'react';
import { ChatPanel } from './ChatPanel';
import { OpsPanel } from './OpsPanel';
import { DetailDrawer } from './DetailDrawer';

export type TabType = 'runs' | 'trace' | 'evals' | 'status';

export function Dashboard() {
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<any | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<'online' | 'offline'>('offline');
  const [activeTab, setActiveTab] = useState<TabType>('runs');
  const [isMobile, setIsMobile] = useState(false);
  const [mobileView, setMobileView] = useState<'chat' | 'ops'>('chat');

  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth < 768);
    };
    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Poll connection health
  useEffect(() => {
    const checkHealth = async () => {
      try {
        const res = await fetch('/api/health');
        if (res.ok) {
          setConnectionStatus('online');
        } else {
          setConnectionStatus('offline');
        }
      } catch {
        setConnectionStatus('offline');
      }
    };
    checkHealth();
    const interval = setInterval(checkHealth, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div style={{ display: 'flex', height: '100vh', width: '100vw', overflow: 'hidden', position: 'relative' }}>
      {isMobile ? (
        // Mobile Toggle Layout
        <div style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100%' }}>
          <div style={{ flex: 1, overflow: 'hidden' }}>
            {mobileView === 'chat' ? (
              <ChatPanel connectionStatus={connectionStatus} activeRunId={activeRunId} />
            ) : (
              <OpsPanel 
                activeTab={activeTab} 
                setActiveTab={setActiveTab} 
                activeRunId={activeRunId} 
                setActiveRunId={setActiveRunId}
                setSelectedEvent={setSelectedEvent}
                connectionStatus={connectionStatus}
              />
            )}
          </div>
          {/* Mobile Bottom Nav */}
          <div style={{ 
            height: '60px', 
            borderTop: '1px solid var(--border-color)', 
            backgroundColor: 'var(--bg-secondary)', 
            display: 'flex', 
            justifyContent: 'space-around', 
            alignItems: 'center' 
          }}>
            <button 
              onClick={() => setMobileView('chat')}
              style={{ 
                background: 'none', 
                border: 'none', 
                color: mobileView === 'chat' ? 'var(--status-info)' : 'var(--text-secondary)',
                fontWeight: mobileView === 'chat' ? 'bold' : 'normal',
                cursor: 'pointer'
              }}
            >
              Chat
            </button>
            <button 
              onClick={() => setMobileView('ops')}
              style={{ 
                background: 'none', 
                border: 'none', 
                color: mobileView === 'ops' ? 'var(--status-info)' : 'var(--text-secondary)',
                fontWeight: mobileView === 'ops' ? 'bold' : 'normal',
                cursor: 'pointer'
              }}
            >
              Ops
            </button>
          </div>
        </div>
      ) : (
        // Desktop Split Screen Layout (Fixed 45% Chat, 55% Ops)
        <>
          <div style={{ width: '45%', borderRight: '1px solid var(--border-color)', overflow: 'hidden' }}>
            <ChatPanel connectionStatus={connectionStatus} activeRunId={activeRunId} />
          </div>
          <div style={{ width: '55%', overflow: 'hidden' }}>
            <OpsPanel 
              activeTab={activeTab} 
              setActiveTab={setActiveTab} 
              activeRunId={activeRunId} 
              setActiveRunId={setActiveRunId}
              setSelectedEvent={setSelectedEvent}
              connectionStatus={connectionStatus}
            />
          </div>
        </>
      )}

      {selectedEvent && (
        <DetailDrawer event={selectedEvent} onClose={() => setSelectedEvent(null)} />
      )}
    </div>
  );
}
