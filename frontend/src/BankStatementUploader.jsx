import React, { useRef, useState } from 'react';

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB
const ACCEPTED_TYPES = [
  'text/csv',
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/pdf',
];
const ACCEPTED_EXTENSIONS = ['.csv', '.xls', '.xlsx', '.pdf'];

function BankStatementUploader() {
  const [file, setFile] = useState(null);
  const [error, setError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [transactions, setTransactions] = useState([]); // NEW: store parsed transactions
  const [meta, setMeta] = useState(null); // NEW: store file meta info
  const [showResult, setShowResult] = useState(false); // NEW: control result display
  const inputRef = useRef();

  const validateFile = (file) => {
    if (!file) return 'No file selected.';
    if (!ACCEPTED_TYPES.includes(file.type) && !ACCEPTED_EXTENSIONS.some(ext => file.name.endsWith(ext))) {
      return 'Invalid file type. Please upload a CSV, Excel, or PDF file.';
    }
    if (file.size > MAX_FILE_SIZE) {
      return 'File size exceeds 10 MB.';
    }
    return '';
  };

  const handleFile = (file) => {
    const validationError = validateFile(file);
    if (validationError) {
      setError(validationError);
      setFile(null);
      setSuccess(false);
      return;
    }
    setFile(file);
    setError('');
    setSuccess(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFile(e.dataTransfer.files[0]);
    }
  };

  const handleChange = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFile(e.target.files[0]);
    }
  };

  const handleBrowse = () => {
    inputRef.current.click();
  };

  const handleShowResult = () => {
    setShowResult(true);
  };

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setError('');
    setSuccess(false);
    setTransactions([]);
    setMeta(null);
    const formData = new FormData();
    formData.append('file', file);
    try {
      const response = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      });
      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || 'Upload failed.');
      }
      const data = await response.json();
      setSuccess(true);
      setTransactions(data.transactions || []);
      setMeta({ filename: data.filename, size: data.size, content_type: data.content_type });
      setFile(null);
    } catch (err) {
      setError(err.message || 'Upload failed.');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div style={{ maxWidth: 700, margin: '2rem auto', padding: 24, border: '1px solid #ccc', borderRadius: 8 }}>
      <div
        onDrop={handleDrop}
        onDragOver={e => e.preventDefault()}
        style={{
          border: '2px dashed #aaa',
          borderRadius: 8,
          padding: 32,
          textAlign: 'center',
          marginBottom: 16,
          background: '#fafafa',
          cursor: 'pointer',
        }}
      >
        Drag & drop your bank statement here<br />
        or <span style={{ color: '#1976d2', textDecoration: 'underline', cursor: 'pointer' }} onClick={handleBrowse}>browse</span> to upload
        <input
          type="file"
          accept={ACCEPTED_EXTENSIONS.join(',')}
          style={{ display: 'none' }}
          ref={inputRef}
          onChange={handleChange}
        />
        <button
          type="button"
          style={{ marginLeft: 16, background: '#888', color: '#fff', border: 'none', borderRadius: 4, padding: '8px 16px', cursor: 'pointer' }}
          onClick={handleShowResult}
          disabled={transactions.length === 0}
        >
          Show Result
        </button>
      </div>
      {file && (
        <div style={{ marginBottom: 8 }}>
          <strong>Selected file:</strong> {file.name} ({(file.size / 1024).toFixed(1)} KB)
        </div>
      )}
      {error && <div style={{ color: 'red', marginBottom: 8 }}>{error}</div>}
      {success && <div style={{ color: 'green', marginBottom: 8 }}>Upload successful!</div>}
      <button
        onClick={handleUpload}
        disabled={!file || uploading}
        style={{
          background: '#1976d2',
          color: '#fff',
          border: 'none',
          borderRadius: 4,
          padding: '8px 16px',
          cursor: !file || uploading ? 'not-allowed' : 'pointer',
          marginTop: 8
        }}
      >
        {uploading ? 'Uploading...' : 'Upload'}
      </button>
      {/* Show parsed transactions only when Show Result is clicked */}
      {showResult && transactions.length > 0 && (
        <div style={{ marginTop: 32 }}>
          <h3>Parsed Transactions</h3>
          {meta && (
            <div style={{ marginBottom: 8, fontSize: 14, color: '#555' }}>
              <strong>File:</strong> {meta.filename} | <strong>Type:</strong> {meta.content_type} | <strong>Size:</strong> {(meta.size/1024).toFixed(1)} KB
            </div>
          )}
          <div style={{ overflowX: 'auto' }}>
            <table style={{ borderCollapse: 'collapse', width: '100%' }}>
              <thead>
                <tr style={{ background: '#f0f0f0' }}>
                  <th style={{ border: '1px solid #ccc', padding: 8 }}>Date</th>
                  <th style={{ border: '1px solid #ccc', padding: 8 }}>Description</th>
                  <th style={{ border: '1px solid #ccc', padding: 8 }}>Debit</th>
                  <th style={{ border: '1px solid #ccc', padding: 8 }}>Credit</th>
                  <th style={{ border: '1px solid #ccc', padding: 8 }}>Balance</th>
                </tr>
              </thead>
              <tbody>
                {transactions.map((row, idx) => (
                  <tr key={idx}>
                    <td style={{ border: '1px solid #ccc', padding: 8 }}>{row.date}</td>
                    <td style={{ border: '1px solid #ccc', padding: 8 }}>{row.description}</td>
                    <td style={{ border: '1px solid #ccc', padding: 8 }}>{row.debit}</td>
                    <td style={{ border: '1px solid #ccc', padding: 8 }}>{row.credit}</td>
                    <td style={{ border: '1px solid #ccc', padding: 8 }}>{row.balance}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

export default BankStatementUploader;
