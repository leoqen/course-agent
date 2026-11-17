export function Icon({ name }: { name: 'plus' | 'arrow' | 'chat' | 'menu' | 'stop' | 'close' }) {
  const paths = {
    plus: 'M12 5v14M5 12h14',
    arrow: 'M12 19V5m-6 6 6-6 6 6',
    chat: 'M21 11a8 8 0 0 1-8 8H6l-4 3V11a9 9 0 0 1 19 0Z',
    menu: 'M4 6h16M4 12h16M4 18h16',
    stop: 'M6 6h12v12H6z',
    close: 'm6 6 12 12M6 18 18 6',
  };
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}
