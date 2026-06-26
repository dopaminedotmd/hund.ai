import type { TabType } from './Dashboard';

interface OpsPanelProps {
  activeTab: TabType;
  setActiveTab: (tab: TabType) => void;
  activeRunId: string | null;
  setActiveRunId: (id: string | null) => void;
  setSelectedEvent: (event: any) => void;
  connectionStatus: string;
}

export function OpsPanel({ activeTab, setActiveTab, activeRunId, setActiveRunId, setSelectedEvent, connectionStatus }: OpsPanelProps) {
  return (
    <div>
      Ops Panel Stub (Tab: {activeTab}, Run: {activeRunId}, Status: {connectionStatus})
      <button onClick={() => setActiveTab('trace')}>Toggle Tab</button>
      <button onClick={() => setActiveRunId('run-1')}>Toggle Run</button>
      <button onClick={() => setSelectedEvent({ id: 1 })}>Select Event</button>
    </div>
  );
}
