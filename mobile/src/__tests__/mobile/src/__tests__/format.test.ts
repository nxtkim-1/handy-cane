import { last7Text } from '../ui/format';

describe('last7Text', () => {
  it('renders a proper empty-data sentence for null', () => {
    const t = last7Text(null);
    expect(t).toBe('Not enough data yet.');
    expect(t).not.toMatch(/no data|null/);
  });
  it('renders the median when present', () => {
    expect(last7Text(42)).toBe('Last 7 days with enough data: 42 min per day (median).');
  });
});
