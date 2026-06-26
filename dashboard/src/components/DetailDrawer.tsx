export function DetailDrawer({ event, onClose }: { event: any; onClose: () => void }) {
  return (
    <div>
      Detail Drawer Stub (Event: {JSON.stringify(event)})
      <button onClick={onClose}>Close</button>
    </div>
  );
}
