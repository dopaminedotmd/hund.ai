interface DetailDrawerProps {
  event: any;
  onClose: () => void;
}

export function DetailDrawer({ event, onClose }: DetailDrawerProps) {
  // Parse payload
  let payload: any = {};
  try {
    payload = typeof event.payload_redacted === 'string' 
      ? JSON.parse(event.payload_redacted) 
      : event.payload_redacted || {};
  } catch {
    payload = event.payload_redacted || {};
  }

  const isVerification = event.event_type === 'verification_completed';

  return (
    <div style={{
      position: 'absolute',
      top: 0,
      right: 0,
      width: '55%',
      height: '100%',
      backgroundColor: 'var(--bg-secondary)',
      borderLeft: '1px solid var(--border-color)',
      boxShadow: '-4px 0 20px rgba(0,0,0,0.5)',
      display: 'flex',
      flexDirection: 'column',
      zIndex: 100,
      animation: 'slideIn var(--transition-speed) ease-out'
    }}>
      {/* Animation definition */}
      <style>{`
        @keyframes slideIn {
          from { transform: translateX(100%); }
          to { transform: translateX(0); }
        }
      `}</style>

      {/* Header */}
      <div style={{ 
        padding: '16px', 
        borderBottom: '1px solid var(--border-color)', 
        display: 'flex', 
        justifyContent: 'space-between',
        alignItems: 'center'
      }}>
        <div>
          <h3 style={{ fontSize: '1rem', fontWeight: 600 }}>Event Detail</h3>
          <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            ID: {event.event_id}
          </p>
        </div>
        <button 
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--text-secondary)',
            fontSize: '1.2rem',
            cursor: 'pointer'
          }}
        >
          ✕
        </button>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
        
        {/* Verification Completed Special Section */}
        {isVerification && (
          <div style={{ 
            padding: '16px', 
            border: '1px solid var(--border-color)', 
            borderRadius: '6px', 
            backgroundColor: 'var(--bg-primary)'
          }}>
            <h4 style={{ fontSize: '0.9rem', marginBottom: '12px', color: 'var(--status-info)' }}>
              Verification Evidence
            </h4>
            
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
              <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Verification Kind:</span>
              <span style={{ 
                fontFamily: 'var(--font-mono)', 
                fontSize: '0.8rem',
                backgroundColor: 'rgba(255,255,255,0.05)',
                padding: '2px 6px',
                borderRadius: '3px'
              }}>
                {payload.verification_kind || 'unknown'}
              </span>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
              <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Exit Code:</span>
              <span style={{ 
                fontFamily: 'var(--font-mono)', 
                fontSize: '0.8rem',
                color: payload.exit_code === 0 ? 'var(--status-success)' : 'var(--status-danger)'
              }}>
                {payload.exit_code !== undefined ? payload.exit_code : 'N/A'}
              </span>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
              <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Result Badge:</span>
              <span style={{ 
                padding: '2px 8px', 
                borderRadius: '4px', 
                fontSize: '0.75rem', 
                fontWeight: 'bold',
                backgroundColor: payload.passed ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                color: payload.passed ? 'var(--status-success)' : 'var(--status-danger)',
                border: `1px solid ${payload.passed ? 'var(--status-success)' : 'var(--status-danger)'}`
              }}>
                {payload.passed ? 'PASS' : 'FAIL'}
              </span>
            </div>

            <div style={{ marginTop: '12px' }}>
              <span style={{ display: 'block', fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                Command:
              </span>
              <div style={{ 
                fontFamily: 'var(--font-mono)', 
                fontSize: '0.8rem', 
                backgroundColor: 'var(--bg-secondary)', 
                padding: '8px', 
                borderRadius: '4px',
                border: '1px solid var(--border-color)',
                wordBreak: 'break-all'
              }}>
                {payload.command || 'None'}
              </div>
            </div>

            {payload.stdout_redacted_summary && (
              <div style={{ marginTop: '12px' }}>
                <span style={{ display: 'block', fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                  Output Summary:
                </span>
                <pre style={{ 
                  fontFamily: 'var(--font-mono)', 
                  fontSize: '0.75rem', 
                  backgroundColor: 'var(--bg-secondary)', 
                  padding: '8px', 
                  borderRadius: '4px',
                  border: '1px solid var(--border-color)',
                  maxHeight: '150px',
                  overflowY: 'auto',
                  whiteSpace: 'pre-wrap'
                }}>
                  {payload.stdout_redacted_summary}
                </pre>
              </div>
            )}
          </div>
        )}

        {/* JSON Viewer */}
        <div>
          <h4 style={{ fontSize: '0.9rem', marginBottom: '8px', color: 'var(--text-secondary)' }}>Raw Event JSON</h4>
          <pre style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.75rem',
            backgroundColor: 'var(--bg-primary)',
            padding: '12px',
            borderRadius: '6px',
            border: '1px solid var(--border-color)',
            overflowX: 'auto',
            whiteSpace: 'pre-wrap'
          }}>
            {JSON.stringify(event, null, 2)}
          </pre>
        </div>

      </div>
    </div>
  );
}
