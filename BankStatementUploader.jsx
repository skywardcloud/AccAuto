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

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setError('');
    setSuccess(false);
    const formData = new FormData();
    formData.append('file', file);
    try {
      const response = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      });
      if (!response.ok) {
        throw new Error('Upload failed.');
      }
      setSuccess(true);
      setFile(null);
    } catch (err) {
      setError(err.message || 'Upload failed.');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div style={{ maxWidth: 400, margin: '2rem auto', padding: 24, border: '1px solid #ccc', borderRadius: 8 }}>
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
        onClick={handleBrowse}
      >
        Drag & drop your bank statement here<br />
        <span style={{ color: '#888', fontSize: 12 }}>
          (CSV, Excel, or PDF, max 10 MB)
        </span>
      </div>
      <input
        type="file"
        accept={ACCEPTED_EXTENSIONS.join(',')}
        style={{ display: 'none' }}
        ref={inputRef}
        onChange={handleChange}
      />
      <button type="button" onClick={handleBrowse} style={{ marginBottom: 16 }}>
        Browse
      </button>
      {file && (
        <div style={{ marginBottom: 8 }}>
          <strong>Selected file:</strong> {file.name} ({file.type || 'Unknown type'})
        </div>
      )}
      {error && <div style={{ color: 'red', marginBottom: 8 }}>{error}</div>}
      {success && <div style={{ color: 'green', marginBottom: 8 }}>Upload successful!</div>}
      <button
        type="button"
        onClick={handleUpload}
        disabled={!file || uploading}
        style={{ width: '100%' }}
      >
        {uploading ? 'Uploading...' : 'Upload'}
      </button>
    </div>
  );
}

export default BankStatementUploader;
