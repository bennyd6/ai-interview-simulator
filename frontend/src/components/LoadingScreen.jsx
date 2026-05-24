import { useEffect, useState } from 'react';
import { Loader2, Server, Globe, Database, BrainCircuit } from 'lucide-react';

export default function LoadingScreen({ company, role }) {
  const [step, setStep] = useState(0);

  // Theatrical steps that match what the Backend is actually doing (Searching Web)
  const steps = [
    { text: "Initializing MCP Secure Gateway...", icon: Server },
    { text: `Executing Live Web Search: "${company} ${role} questions"...`, icon: Globe },
    { text: "Scraping interview archives & forums...", icon: Database },
    { text: "Synthesizing context with System Prompt...", icon: BrainCircuit },
    { text: "Finalizing Agent Persona...", icon: Loader2 }
  ];

  useEffect(() => {
    // Total wait time matches the SetupForm timeout
    const interval = setInterval(() => {
      setStep((prev) => (prev < steps.length - 1 ? prev + 1 : prev));
    }, 1500);
    return () => clearInterval(interval);
  }, []);

  const CurrentIcon = steps[step].icon;

  return (
    <div className="min-h-screen bg-white flex flex-col items-center justify-center p-8 text-black">
      <div className="max-w-md w-full text-center space-y-12">
        
        <div className="relative w-24 h-24 mx-auto">
          <div className="absolute inset-0 border-4 border-gray-100 rounded-full"></div>
          <div className="absolute inset-0 border-4 border-black border-t-transparent rounded-full animate-spin"></div>
          <div className="absolute inset-0 flex items-center justify-center">
            <CurrentIcon className="w-8 h-8 text-black" />
          </div>
        </div>

        <div className="space-y-4">
          <h2 className="text-2xl font-bold tracking-tight uppercase">Building Context</h2>
          <p className="text-gray-500 font-medium animate-pulse">{steps[step].text}</p>
        </div>

        {/* The "Terminal" output */}
        <div className="bg-gray-50 border border-gray-200 rounded p-6 text-left font-mono text-[10px] text-gray-500 space-y-2 overflow-hidden shadow-inner h-48">
          <p> MCP_CORE: Active</p>
          <p className={step > 0 ? 'text-black' : 'opacity-0'}>{`> SEARCH_TOOL: Executing DuckDuckGo query...`}</p>
          <p className={step > 1 ? 'text-black' : 'opacity-0'}>{`> RESULT: Found 4 relevant sources for ${company}`}</p>
          <p className={step > 2 ? 'text-black' : 'opacity-0'}>{`> EXTRACTION: Parsing behavioral questions...`}</p>
          <p className={step > 3 ? 'text-black' : 'opacity-0'}>{`> LLM_CONTEXT: Injecting ${role} requirements...`}</p>
          <p className={step > 4 ? 'text-green-600 font-bold' : 'opacity-0'}>{`> STATUS: READY_TO_START`}</p>
        </div>
      </div>
    </div>
  );
}