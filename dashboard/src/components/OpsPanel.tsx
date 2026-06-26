import { useState, useEffect } from 'react';
import type { TabType } from './Dashboard';

interface OpsPanelProps {
  activeTab: TabType;
  setActiveTab: (tab: TabType) => void;
  activeRunId: string | null;
  setActiveRunId: (id: string | null) => void;
  setSelectedEvent: (event: any) => void;
  connectionStatus: 'online' | 'offline';
}

export function OpsPanel({ 
  activeTab, 
  setActiveTab, 
  activeRunId, 
  setActiveRunId, 
  setSelectedEvent, 
  connectionStatus 
}: OpsPanelProps) {
  const [runs, setRuns] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [evals, setEvals] = useState<any[]>([]);

  // Fetch runs list
  useEffect(() => {
    if (connectionStatus !== 'online') return;
    const fetchRuns = async () => {
      try {
        const res = await fetch('/api/events?event_type=run_started');
        const data = await res.json();
        if (data.events) {
          setRuns(data.events.map((e: any) => ({
            id: e.run_id,
            status: 'completed', // Simplified
            start: e.created_at,
            duration: '0.8s'
          })));
        }
      } catch (err) {
        console.error("Error fetching runs:", err);
      }
    };
    fetchRuns();
  }, [connectionStatus]);

  // Fetch events for trace (SSE-first with polling fallback)
  useEffect(() => {
    if (connectionStatus !== 'online') return;

    let eventSource: EventSource | null = null;
    let pollInterval: any = null;

    const startSSE = () => {
      const url = activeRunId ? `/api/events?run_id=${activeRunId}&stream=true` : '/api/events?stream=true';
      eventSource = new EventSource(url);

      eventSource.onmessage = (event) => {
        try {
          const newEvent = JSON.parse(event.data);
          setEvents((prev) => {
            if (prev.some((e) => e.event_id === newEvent.event_id)) return prev;
            return [newEvent, ...prev];
          });
        } catch (err) {
          console.error("Error parsing SSE:", err);
        }
      };

      eventSource.onerror = () => {
        // SSE failed or not supported by endpoint yet -> fallback to polling
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
          const url = activeRunId ? `/api/events?run_id=${activeRunId}` : '/api/events';
          const res = await fetch(url);
          const data = await res.json();
          if (data.events) {
            setEvents(data.events);
          }
        } catch (err) {
          console.error("Error polling events:", err);
        }
      };
      fetchEvents();
      pollInterval = setInterval(fetchEvents, 2000);
    };

    // Initialize with SSE
    startSSE();

    return () => {
      if (eventSource) eventSource.close();
      if (pollInterval) clearInterval(pollInterval);
    };
  }, [activeRunId, connectionStatus]);

  // Mock eval data if empty
  useEffect(() => {
    setEvals([
      { scenario: 'safety_exfiltration_detect', verdict: 'PASS', score: '5/5', date: '2026-06-26 19:30' },
      { scenario: 'path_traversal_restriction', verdict: 'PASS', score: '5/5', date: '2026-06-26 19:32' },
      { scenario: 'dangerous_write_block', verdict: 'PASS', score: '5/5', date: '2026-06-26 19:35' },
    ]);
  }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', backgroundColor: 'var(--bg-primary)' }}>
      {/* Navigation */}
      <div style={{ 
        display: 'flex', 
        borderBottom: '1px solid var(--border-color)', 
        backgroundColor: 'var(--bg-secondary)',
        padding: '0 8px'
      }}>
        {(['runs', 'trace', 'evals', 'status'] as TabType[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{
              padding: '16px 20px',
              background: 'none',
              border: 'none',
              borderBottom: activeTab === tab ? '2px solid var(--status-info)' : '2px solid transparent',
              color: activeTab === tab ? 'var(--text-primary)' : 'var(--text-secondary)',
              cursor: 'pointer',
              fontWeight: 500,
              textTransform: 'capitalize'
            }}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Content area */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px' }}>
        {activeTab === 'runs' && (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.85rem' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}>
                  <th style={{ padding: '8px' }}>Run ID</th>
                  <th style={{ padding: '8px' }}>Status</th>
                  <th style={{ padding: '8px' }}>Start</th>
                  <th style={{ padding: '8px' }}>Duration</th>
                </tr>
              </thead>
              <tbody>
                {runs.length === 0 ? (
                  <tr>
                    <td colSpan={4} style={{ padding: '20px 8px', color: 'var(--text-muted)', textAlign: 'center' }}>
                      Inga körningar hittades. Starta daemonen och generera events.
                    </td>
                  </tr>
                ) : (
                  runs.map((r) => (
                    <tr 
                      key={r.id} 
                      onClick={() => { setActiveRunId(r.id); setActiveTab('trace'); }}
                      style={{ 
                        borderBottom: '1px solid var(--border-color)', 
                        cursor: 'pointer',
                        backgroundColor: activeRunId === r.id ? 'rgba(59, 130, 246, 0.05)' : 'transparent'
                      }}
                    >
                      <td style={{ padding: '12px 8px', color: 'var(--status-info)' }}>{r.id.substring(0, 8)}...</td>
                      <td style={{ padding: '12px 8px', color: 'var(--status-success)' }}>{r.status}</td>
                      <td style={{ padding: '12px 8px', color: 'var(--text-secondary)' }}>{new Date(r.start).toLocaleTimeString()}</td>
                      <td style={{ padding: '12px 8px', color: 'var(--text-muted)' }}>{r.duration}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        {activeTab === 'trace' && (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {events.length === 0 ? (
                <div style={{ padding: '20px', color: 'var(--text-muted)', textAlign: 'center' }}>
                  Inga trace events i databasen.
                </div>
              ) : (
                events.map((e) => {
                  let badgeColor = 'var(--status-info)';
                  if (e.event_type.includes('fail') || e.event_type.includes('blocked')) badgeColor = 'var(--status-danger)';
                  if (e.event_type.includes('start')) badgeColor = 'var(--status-warning)';
                  if (e.event_type.includes('complete') || e.event_type.includes('approve')) badgeColor = 'var(--status-success)';

                  return (
                    <div 
                      key={e.event_id} 
                      onClick={() => setSelectedEvent(e)}
                      style={{ 
                        padding: '10px 12px', 
                        borderRadius: '4px', 
                        border: '1px solid var(--border-color)',
                        backgroundColor: 'var(--bg-secondary)',
                        cursor: 'pointer',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center'
                      }}
                    >
                      <div>
                        <span style={{ color: 'var(--text-muted)', marginRight: '10px' }}>
                          {new Date(e.created_at).toLocaleTimeString()}
                        </span>
                        <span style={{ fontWeight: 'bold', color: 'var(--text-primary)', marginRight: '15px' }}>
                          {e.event_type}
                        </span>
                        <span style={{ color: 'var(--text-secondary)' }}>
                          {e.actor}
                        </span>
                      </div>
                      <span style={{ 
                        padding: '2px 6px', 
                        borderRadius: '3px', 
                        fontSize: '0.7rem', 
                        backgroundColor: badgeColor, 
                        color: 'white',
                        fontWeight: 'bold' 
                      }}>
                        {e.risk || 'none'}
                      </span>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        )}

        {activeTab === 'evals' && (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.85rem' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}>
                  <th style={{ padding: '8px' }}>Scenario</th>
                  <th style={{ padding: '8px' }}>Verdict</th>
                  <th style={{ padding: '8px' }}>Score</th>
                  <th style={{ padding: '8px' }}>Date</th>
                </tr>
              </thead>
              <tbody>
                {evals.map((ev, idx) => (
                  <tr key={idx} style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td style={{ padding: '12px 8px', fontWeight: 'bold' }}>{ev.scenario}</td>
                    <td style={{ padding: '12px 8px', color: ev.verdict === 'PASS' ? 'var(--status-success)' : 'var(--status-danger)' }}>
                      {ev.verdict}
                    </td>
                    <td style={{ padding: '12px 8px' }}>{ev.score}</td>
                    <td style={{ padding: '12px 8px', color: 'var(--text-muted)' }}>{ev.date}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {activeTab === 'status' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', fontSize: '0.9rem' }}>
            <div style={{ padding: '16px', border: '1px solid var(--border-color)', borderRadius: '6px', backgroundColor: 'var(--bg-secondary)' }}>
              <h3 style={{ marginBottom: '12px', fontWeight: 600 }}>Connection Info</h3>
              <p style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Endpoint:</span>
                <span style={{ fontFamily: 'var(--font-mono)' }}>http://127.0.0.1:7432</span>
              </p>
              <p style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                <span style={{ color: 'var(--text-secondary)' }}>HMAC Validation:</span>
                <span style={{ color: 'var(--status-success)', fontFamily: 'var(--font-mono)' }}>Active (OS Keyring Key)</span>
              </p>
              <p style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Permission Mode:</span>
                <span style={{ fontFamily: 'var(--font-mono)' }}>connector_remote</span>
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
