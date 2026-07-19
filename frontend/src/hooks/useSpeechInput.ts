import { useCallback, useEffect, useRef, useState } from "react";

/** Browser-native voice input (Web Speech API). No backend, no cost.
 * Chrome's recognition is server-backed: needs network + secure context
 * (localhost qualifies). Absent support → `supported: false`, render no mic. */
export function useSpeechInput(onFinalText: (text: string) => void) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const Recognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
  const supported = Boolean(Recognition);

  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null);

  useEffect(() => {
    return () => recognitionRef.current?.abort?.();
  }, []);

  const start = useCallback(() => {
    if (!supported || listening) return;
    const rec = new Recognition();
    rec.continuous = false;
    rec.interimResults = true;
    rec.lang = navigator.language || "en-US";

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    rec.onresult = (event: any) => {
      let interimText = "";
      let finalText = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) finalText += transcript;
        else interimText += transcript;
      }
      setInterim(interimText);
      if (finalText) onFinalText(finalText.trim());
    };
    rec.onend = () => {
      setListening(false);
      setInterim("");
    };
    rec.onerror = () => {
      setListening(false);
      setInterim("");
    };

    recognitionRef.current = rec;
    setListening(true);
    rec.start();
  }, [Recognition, supported, listening, onFinalText]);

  const stop = useCallback(() => {
    recognitionRef.current?.stop?.();
  }, []);

  return { supported, listening, interim, start, stop };
}
