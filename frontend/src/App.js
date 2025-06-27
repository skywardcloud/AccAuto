import logo from './logo.svg';
import './App.css';
import BankStatementUploader from './BankStatementUploader';

function App() {
  return (
    <div className="App">
      <header className="App-header">
        <img src={logo} className="App-logo" alt="logo" />
        <h2>Bank Statement Uploader</h2>
        <BankStatementUploader />
      </header>
    </div>
  );
}

export default App;
