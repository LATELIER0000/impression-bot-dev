@echo off
setlocal

:: Nom du fichier de sortie
set "OUTPUT_FILE=code_projet.txt"

echo.
echo ==========================================================
echo  GENERATION DU FICHIER DE CODE SPECIFIQUE
echo ==========================================================
echo.
echo Fichier de sortie : %OUTPUT_FILE%
echo.
echo Lancement du processus...

:: Vide le fichier de sortie et ajoute un en-tête
echo --- CODE DU PROJET - GENERE LE %DATE% A %TIME% --- > %OUTPUT_FILE%
echo. >> %OUTPUT_FILE%

:: Liste EXACTE des fichiers à inclure
:: Note : J'utilise *.sql car tu as dit "un fichier SQL". Si tu en as plusieurs, remplace *.sql par le nom exact (ex: "database.sql").
set "FILES_TO_PROCESS=config.py print_server.py *.sql static\css\style.css static\js\admin.js static\js\main.js templates\index.html templates\admin.html"

:: Boucle sur chaque fichier de la liste
for %%F in (%FILES_TO_PROCESS%) do (
    
    :: Vérifie si le fichier existe avant de l'ajouter
    if exist "%%F" (
        echo Ajout du fichier : "%%F"
        
        :: Ajoute le nom du fichier comme titre dans le fichier de sortie
        echo. >> %OUTPUT_FILE%
        echo ======================================================= >> %OUTPUT_FILE%
        echo FICHIER : %%F >> %OUTPUT_FILE%
        echo ======================================================= >> %OUTPUT_FILE%
        echo. >> %OUTPUT_FILE%

        :: Ajoute le contenu du fichier
        type "%%F" >> %OUTPUT_FILE%

        :: Ajoute deux sauts de ligne pour séparer les fichiers
        echo. >> %OUTPUT_FILE%
        echo. >> %OUTPUT_FILE%
    ) else (
        echo ATTENTION: Le fichier "%%F" n'a pas ete trouve et a ete ignore.
    )
)

echo.
echo ==========================================================
echo  PROCESSUS TERMINE !
echo.
echo Le fichier '%OUTPUT_FILE%' a ete cree avec succes.
echo Il contient uniquement les fichiers specifies.
echo ==========================================================
echo.
pause