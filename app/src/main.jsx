import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import './styles.css';

// no StrictMode: the WebGL engine must initialise exactly once
createRoot(document.getElementById('root')).render(<App />);
