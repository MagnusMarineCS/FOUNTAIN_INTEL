# EVE Intel Dashboard

A real-time, browser-based intelligence dashboard for EVE Online, designed to monitor chat logs for hostile activity and display it on a tactical map of the Fountain region.

This tool provides at-a-glance situational awareness by parsing intel channels for system names, pilot names, and ship types, and then visualizing that information with color-coded alerts and map highlights.

## Features

*   **Real-time Log Monitoring:** A Python backend continuously watches EVE chat log files for new messages.
*   **Dynamic Alert System:** The UI features a prominent "traffic light" bar that changes color based on threat proximity (Green, Yellow, Red).
*   **Spike Alerts:** Special handling for "SPIKE" reports, with unique visual and text notifications.
*   **Interactive 2D Map:** A pannable and zoomable map of the Fountain region, showing all systems and connections.
*   **Jump Route Planning:** Click any system on the map to see the shortest jump route from your current location.
*   **Jump Bridge Overlay:** Toggle a view of the jump bridge network to find the fastest routes.
*   **Automated System Tracking:** Automatically detects your current system by monitoring the `Local` chat log.
*   **Ship & System Search:** A powerful search bar to quickly find systems on the map or look up detailed ship information.
*   **Detailed Ship Info:** Click on a ship name in the log feed to see its class, faction, and role bonuses, complete with rotating hull images.
*   **User-Friendly Setup:** On first run, the backend prompts the user to graphically select their EVE log directory.
*   **Customizable Settings:** An in-app settings panel allows users to configure alert distances, sound volume, and UI features like alert flashing.
*   **Test Mode:** A built-in test mode allows users to simulate Red, Yellow, and Spike alerts to familiarize themselves with the system.

## Setup & Installation

### Prerequisites

*   Python 3.x
*   A modern web browser (Chrome, Firefox, Edge)

### For Users (Recommended)

1.  **Download the Project:** On the main repository page, click the green `<> Code` button and select `Download ZIP`. Unzip the file to a folder on your computer.
2.  **Install Dependencies:** This project requires the `websockets` library. Open a terminal or command prompt and run:
    ```
    pip install websockets
    ```
3.  **Run the Backend:** In the folder where you unzipped the project, run the backend server from your terminal:
    ```
    python intel_backend.py
    ```
    *   On the very first run, a window will pop up asking you to **select your EVE Online `Chatlogs` directory**. This is typically located in `Documents\EVE\logs\Chatlogs`. Once selected, this setting will be saved.

4.  **Open the Dashboard:** Open the `EVE_Intel_Dashboard.html` file in your web browser. It will automatically connect to the running backend.

---

### For Developers (Building from Source)

If you want to modify the frontend code, you will need to rebuild the final HTML file.

1.  Follow steps 1 and 2 from the User instructions above.
2.  Modify the source files (`index.html`, etc.) as needed.
3.  When you are ready to see your changes, run the build script from your terminal:
    ```
    python build.py
    ```
4.  Open the **newly generated** `EVE_Intel_Dashboard.html` file to see your changes.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
