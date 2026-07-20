/*
 * ESP32 Dual Core Test
 * 
 * This sketch demonstrates the dual-core capabilities of the ESP32.
 * It creates two tasks and pins them to different cores (Core 0 and Core 1).
 * Each task will print its name and the core it's currently running on.
 */

TaskHandle_t Task1;
TaskHandle_t Task2;

// Task 1: Will run on Core 0
void Task1code( void * pvParameters ){
  Serial.print("Task1 running on core ");
  Serial.println(xPortGetCoreID());

  for(;;){
    Serial.print("Task1 (Core 0) is working... [Time: ");
    Serial.print(millis());
    Serial.println("ms]");
    delay(1000); // Simple delay for visibility
  } 
}

// Task 2: Will run on Core 1
void Task2code( void * pvParameters ){
  Serial.print("Task2 running on core ");
  Serial.println(xPortGetCoreID());

  for(;;){
    Serial.print("Task2 (Core 1) is working... [Time: ");
    Serial.print(millis());
    Serial.println("ms]");
    delay(1500); // Different interval to show parallelism
  }
}

void setup() {
  Serial.begin(115200); 

  // Create Task 1 and pin it to Core 0
  xTaskCreatePinnedToCore(
                    Task1code,   /* Task function. */
                    "Task1",     /* name of task. */
                    10000,       /* Stack size of task */
                    NULL,        /* parameter of the task */
                    1,           /* priority of the task */
                    &Task1,      /* Task handle to keep track of created task */
                    0);          /* pin task to core 0 */                  
  delay(500); 

  // Create Task 2 and pin it to Core 1
  xTaskCreatePinnedToCore(
                    Task2code,   /* Task function. */
                    "Task2",     /* name of task. */
                    10000,       /* Stack size of task */
                    NULL,        /* parameter of the task */
                    1,           /* priority of the task */
                    &Task2,      /* Task handle to keep track of created task */
                    1);          /* pin task to core 1 */
    delay(500); 
}

void loop() {
  // The default loop() typically runs on Core 1
  // We can also print from here to see it in action
  static unsigned long lastPrint = 0;
  if (millis() - lastPrint > 2000) {
    Serial.print("Main Loop running on core ");
    Serial.println(xPortGetCoreID());
    lastPrint = millis();
  }
}
