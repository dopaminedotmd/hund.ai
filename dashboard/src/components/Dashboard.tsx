import { useState, useEffect } from 'react';
import { Sidebar } from './common/Sidebar';
import { HeaderBar } from './common/HeaderBar';
import { AgentHub } from './dashboard/AgentHub';
import { ChatPanel } from './ChatPanel';
import { WidgetGrid } from './dashboard/WidgetGrid';
import { FileExplorer } from './file-explorer/FileExplorer';
import { SettingsPanel } from './settings/SettingsPanel';
import { GrainOverlay } from './common/GrainOverlay';
import { DoubleBezel } from './common/DoubleBezel';

export type TabType = 'runs' | 'trace' | 'evals' | 'status';

export function Dashboard() {
  const [activeView, setActiveView] = useState<'dashboard' | 'files' | 'settings'>('dashboard');
  const [isEditingGrid, setIsEditingGrid] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<'online' | 'offline'>('offline');
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [events, setEvents] = useState<any[]>([]);

  // Logga ut handler (skickar användaren tillbaka till login)
  const handleLogout = () => {
    // Vi lägger en trigger i localStorage som App.tsx lyssnar på för att gå till inloggningssidan
    localStorage.setItem('hund_auth_state', 'logged_out');
    window.location.reload();
  };

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

  // Hämta event logs från connector backend (för Activity Feed widget)
  useEffect(() => {
    if (connectionStatus !== 'online') return;

    let eventSource: EventSource | null = null;
    let pollInterval: any = null;

    const startSSE = () => {
      eventSource = new EventSource('/api/events?stream=true');

      eventSource.onmessage = (event) => {
        try {
          const newEvent = JSON.parse(event.data);
          setEvents((prev) => {
            if (prev.some((e) => e.event_id === newEvent.event_id)) return prev;
            return [newEvent, ...prev];
          });
          if (newEvent.run_id) {
            setActiveRunId(newEvent.run_id);
          }
        } catch (err) {
          console.error("Error parsing SSE:", err);
        }
      };

      eventSource.onerror = () => {
        if (eventSource) {
          eventSource.close();
          eventSource = null;
        }
        startPolling();
      };
    };

    const startPolling = () => {
      const fetchEvents = async () => {
        try {
          const res = await fetch('/api/events');
          const data = await res.json();
          if (data.events) {
            setEvents(data.events);
            if (data.events.length > 0 && data.events[0].run_id) {
              setActiveRunId(data.events[0].run_id);
            }
          }
        } catch (err) {
          console.error("Error polling events:", err);
        }
      };
      fetchEvents();
      pollInterval = setInterval(fetchEvents, 4000);
    };

    startSSE();

    return () => {
      if (eventSource) eventSource.close();
      if (pollInterval) clearInterval(pollInterval);
    };
  }, [connectionStatus]);

  // AI handlingar från filutforskaren till chatten
  const handleTriggerAiAction = (actionText: string) => {
    if ((window as any).sendToHundChat) {
      (window as any).sendToHundChat(actionText);
    }
  };

  const renderMainContent = () => {
    switch (activeView) {
      case 'files':
        return <FileExplorer onTriggerAiAction={handleTriggerAiAction} />;
      case 'settings':
        return <SettingsPanel />;
      case 'dashboard':
      default:
        return (
          <div style={{ 
            display: 'flex', 
            flexDirection: 'column', 
            gap: '24px', 
            width: '100%', 
            paddingBottom: '32px',
            overflowY: 'auto'
          }} className="dark-scrollbar">
            
            {/* Header / Config Bar för Grid */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0 32px', marginTop: '24px' }}>
              <h3 style={{
                fontSize: '12px',
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                color: 'var(--text-secondary)'
              }}>
                Dashboard Layout
              </h3>
              <button
                onClick={() => setIsEditingGrid(!isEditingGrid)}
                style={{
                  padding: '6px 16px',
                  borderRadius: 'var(--radius-pill)',
                  backgroundColor: isEditingGrid ? 'var(--element-active)' : 'var(--element-inactive)',
                  color: isEditingGrid ? '#FFFFFF' : 'var(--text-primary)',
                  fontWeight: 600,
                  fontSize: '13px',
                  border: 'none',
                  cursor: 'pointer',
                  transition: 'all 200ms ease'
                }}
              >
                {isEditingGrid ? 'Spara layout' : 'Anpassa widgets'}
              </button>
            </div>

            {/* Widgets Grid Section */}
            <WidgetGrid 
              isEditing={isEditingGrid} 
              onSendMessage={(msg) => {
                if ((window as any).sendToHundChat) {
                  (window as any).sendToHundChat(msg);
                }
              }}
              events={events}
            />

            {/* Bento Split (40/60) Section */}
            <div style={{ 
              display: 'grid', 
              gridTemplateColumns: '4fr 6fr', 
              gap: '24px', 
              padding: '0 32px',
              height: '560px',
              minHeight: '560px',
              width: '100%'
            }}>
              
              {/* Agent Hub (40%) */}
              <DoubleBezel variant="surface" className="h-full">
                <AgentHub onSendMessage={(msg) => {
                  if ((window as any).sendToHundChat) {
                    (window as any).sendToHundChat(msg);
                  }
                }} />
              </DoubleBezel>
              
              {/* Hund Chat (60%) */}
              <DoubleBezel variant="terminal" className="h-full">
                <ChatPanel 
                  connectionStatus={connectionStatus} 
                  activeRunId={activeRunId} 
                  onSendMessageExternal={() => {}}
                />
              </DoubleBezel>

            </div>

          </div>
        );
    }
  };

  return (
    <div style={{ display: 'flex', height: '100vh', width: '100vw', overflow: 'hidden', position: 'relative' }}>
      <GrainOverlay />
      
      {/* Sidebar (alltid synlig till vänster) */}
      <Sidebar activeView={activeView} setActiveView={setActiveView} onLogout={handleLogout} />

      {/* Content wrapper */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
        
        {/* Header (alltid synlig högst upp) */}
        <HeaderBar connectionStatus={connectionStatus} title={activeView === 'dashboard' ? 'Hund Dashboard' : (activeView === 'files' ? 'Projektarkiv' : 'Systeminställningar')} />
        
        {/* Huvudinnehåll */}
        <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
          {renderMainContent()}
        </div>

      </div>
    </div>
  );
}
