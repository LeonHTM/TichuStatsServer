## **TichuStats Server**
[TichuStats](https://github.com/LeonHTM/TichuStats) is the ultimate Companion app for the popular card game Tichu. This is the Server Logic talking to the clients and an Admin Webpage.

## **Features**
- Accesses MySQL Database to store data in Tables and makes it accessible via routes to clients
- Keeps History of Games, Statistics and Elo Rating across 5 different Timeframes and delivers them based on users timezone
- Stores Profile Images
- Hosts Webpages for Admin Access on the Web, which can interact with some of the routes designed for the Client
- Handles Notifications
- Handles Passkeys

## **Code**
Split into Logic, Routes, Static, Templates and Uploads.
- Logic: All the Classes and Calculations for Profiles, Games, Rounds, Passkeys and Notifications
- Routes: All the Routes accessible by the Client and Admin Page
- Static: Images and CSS for Webpages
- Templates: HTML Pages
- Uploads: Stores the Profile Images of Users

Everything runs in tichuServer.py which also hosts the most important routes.

If you want to know more about the Config.py [contact me](mailto:leon@tichu.dev).

**Hint:** The Help of AI was used on this Project
