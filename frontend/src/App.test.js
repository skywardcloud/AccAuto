import { render, screen } from '@testing-library/react';
import App from './App';

test('renders Bank Statement Uploader header', () => {
  render(<App />);
  const headerElement = screen.getByText(/Bank Statement Uploader/i);
  expect(headerElement).toBeInTheDocument();
});
