
//  Original code credits: 2022/06/03 Radio pliers http://radiopench.blog96.fc2.com/blog-entry-1184.html

void performFFT()
{
  // Prepare FFT calculation data (1.7ms)
  for (int i = 0; i < SAMPLE_BUFFER_SIZE; i++) {
    //vReal[i] = wave[i]; //(wave[i] - 2048) * 3.3 / 4096.0; // convert to voltage
    vReal[i] = wave[i] * 3.3 / 4096.0; // convert to voltage
    vImag[i] = 0;
  }
 
  // Calculate FFT (v2.x API)
  FFT.windowing(FFTWindow::Hamming, FFTDirection::Forward);
  FFT.compute(FFTDirection::Forward);
  FFT.complexToMagnitude();
}