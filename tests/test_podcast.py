import unittest
import os
import wave
from pathlib import Path

class TestPodcastJingle(unittest.TestCase):
    def setUp(self):
        self.test_wav_path = Path("./test_jingle.wav")
        if self.test_wav_path.exists():
            self.test_wav_path.unlink()

    def tearDown(self):
        if self.test_wav_path.exists():
            self.test_wav_path.unlink()

    def test_jingle_generation(self):
        import wave
        import math
        import struct
        
        sample_rate = 22050
        duration = 1.0  # Keep it short (1 second) for fast testing
        num_samples = int(sample_rate * duration)
        
        self.assertFalse(self.test_wav_path.exists())
        
        # Write WAV file
        with wave.open(str(self.test_wav_path.resolve()), "w") as wav_file:
            wav_file.setparams((1, 2, sample_rate, num_samples, "NONE", "not compressed"))
            for i in range(num_samples):
                t = i / sample_rate
                if t < 0.5:
                    freq = 440.0
                else:
                    freq = 554.37
                envelope = max(0.0, 1.0 - t)
                val = 0.5 * math.sin(2.0 * math.pi * freq * t)
                sample = int(val * envelope * 32767)
                wav_file.writeframes(struct.pack("<h", sample))
                
        self.assertTrue(self.test_wav_path.exists())
        self.assertGreater(self.test_wav_path.stat().st_size, 0)
        
        # Verify WAV format parameters
        with wave.open(str(self.test_wav_path.resolve()), "r") as r:
            self.assertEqual(r.getnchannels(), 1)
            self.assertEqual(r.getsampwidth(), 2)
            self.assertEqual(r.getframerate(), sample_rate)

if __name__ == "__main__":
    unittest.main()
