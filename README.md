1. https://event.supercell.com/clashofclans öffnen (in Chrome aber nicht pflicht) & einloggen
2. f12 drücken
3. network tab öffnen
4. filter auf socket setzen
5. f5 drücken
6. den eintrag mit ?token=xyz anklicken
7. im header den host kopieren zb: lb2.socketserver.clashesports.supercell.com:29049 ggf. siehe screenshot
https://github.com/neraxor/coc/blob/main/network.jpg
8. im payload das token kopieren (oder im request url alles nach token= ) ggf. siehe screenshot
https://github.com/neraxor/coc/blob/main/network.jpg
9. im programm bei server den entsprechenden host eintragen wie zb wss://lb2.socketserver.clashesports.supercell.com:29049/?token= (Achtung anfang und ende muss gleich bleiben nur die URL ggf. anpassen)
10. token aus schritt 6 eingeben
11. start drücken

https://github.com/neraxor/coc/blob/main/programm.jpg
