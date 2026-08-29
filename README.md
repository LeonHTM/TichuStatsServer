## **TichuStats Server **
[TichuStats](https://github.com/LeonHTM/TichuStats) is the ultimate Companion app for the popular card game Tichu. This is the Server Logic talking to the clients and an Admin Webpage.

## **Features**
- Acceses MySQL Database to store data in Tables and makes it acceciable via routes to clients
- Calculates Games, Statistics acress Timeframes and Changes in Elo
- Stores Profile Images 
- Hosts Webpages for Admin Acces on the Web, which can interact with some of the Pages designed for the Client
- Handles Notifications 

## **Code**
Split into Logic, Routes, Static, Templates and Uploads. 
- Logic: All the Classes and Calculations for Profiles, Games, Rounds and Notifications
- Routes: All the Routes accessible by the Client and Admin Page
- Static: Images and CSS for Webpages
- Templates: HTML Pages 
- Uploads: Stores the Profile Images of Users

Everything runs in tichuServer.py which also hosts some of the most important Paths.

If you want to know about the Config.py [contact me](mailto:leon@tichu.dev).

