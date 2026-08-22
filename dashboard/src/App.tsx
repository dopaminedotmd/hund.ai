import { useState } from 'react';
import { AnimatePresence } from 'framer-motion';
import { LoginScreen } from './components/login/LoginScreen';
import { TransitionOverlay } from './components/login/TransitionOverlay';
import { Dashboard } from './components/Dashboard';

type PhaseType = 'login' | 'transition' | 'dashboard';

function App() {
  const [phase, setPhase] = useState<PhaseType>(() => {
    // Om användaren redan är inloggad, hoppa direkt till dashboard
    const authState = localStorage.getItem('hund_auth_state');
    return authState === 'logged_in' ? 'dashboard' : 'login';
  });

  const handleLoginSuccess = () => {
    setPhase('transition');
    localStorage.setItem('hund_auth_state', 'logged_in');
    
    // Efter att scroll-övergången har påbörjats, mounta dashboard efter 1.2 sekunder
    setTimeout(() => {
      setPhase('dashboard');
    }, 1200);
  };

  return (
    <div style={{ width: '100vw', height: '100vh', overflow: 'hidden', position: 'relative' }}>
      
      {/* 1. Login Screen */}
      {phase === 'login' && (
        <LoginScreen onLoginSuccess={handleLoginSuccess} />
      )}

      {/* 2. Scroll-övergång */}
      <AnimatePresence>
        {phase === 'transition' && (
          <TransitionOverlay />
        )}
      </AnimatePresence>

      {/* 3. Dashboard */}
      {phase === 'dashboard' && (
        <Dashboard />
      )}
      
    </div>
  );
}

export default App;
