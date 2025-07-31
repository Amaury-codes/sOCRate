# sOCRate - Automatisation Intelligente de l'OCR

<img width="550" alt="ChatGPT Image 31 juil  2025, 14_17_59 copie-modified" src="https://github.com/user-attachments/assets/45e4d79d-2084-4450-b19c-12d791c499c9" />


**sOCRate** est une application de bureau moderne et élégante conçue pour automatiser entièrement le processus de reconnaissance optique de caractères (OCR) sur vos documents PDF. Déposez simplement vos fichiers dans un dossier surveillé, et sOCRate les rendra "cherchables" en ajoutant une couche de texte invisible, tout en préservant la qualité du document original.

---

## ✨ Fonctionnalités Clés

*   **Surveillance en temps réel :** Surveille un ou plusieurs dossiers et traite automatiquement les nouveaux PDF.
*   **OCR Puissant et Précis :** Utilise le moteur Tesseract pour une reconnaissance de haute qualité, avec support multilingue (Français, Anglais, Portugais).
*   **Superposition Intelligente :** Ajoute une couche de texte invisible **sans recréer ou dégrader** le PDF original, garantissant une augmentation de taille minimale.
*   **Traitement Parallèle Robuste :** Traite jusqu'à 3 documents simultanément sans surcharger le système, grâce à une gestion intelligente des tâches.
*   **Règles de Nommage Flexibles :** Personnalisez entièrement le nom des fichiers traités avec des jetons dynamiques (`[NOM_ORIGINAL]`, `[DATE]`, `[COMPTEUR]`, etc.).
*   **Gestion Automatisée des Fichiers :** Choisissez de conserver, déplacer ou écraser les fichiers originaux après traitement.
*   **Interface Moderne :** Une interface utilisateur épurée et professionnelle développée en PyQt6, avec un thème sombre et des contrôles intuitifs.
*   **100% Autonome :** L'application compilée embarque toutes ses dépendances (y compris Tesseract et les packs de langues). Aucune installation manuelle requise pour l'utilisateur final.

---

## 🛠️ Technologies Utilisées

*   **Interface Graphique :** [PyQt6](https://www.riverbankcomputing.com/software/pyqt/)
*   **Moteur OCR :** [Tesseract](https://github.com/tesseract-ocr/tesseract) via `pytesseract`
*   **Manipulation de PDF :** [PyMuPDF (fitz)](https://pymupdf.readthedocs.io/en/latest/)
*   **Surveillance de Fichiers :** [Watchdog](https://github.com/gorakhargosh/watchdog)
*   **Compilation :** [PyInstaller](https://www.pyinstaller.org/)
*   **Automatisation du Build :** GitHub Actions

---

## 🚀 Installation et Utilisation

Les versions compilées pour Windows et macOS sont disponibles directement depuis la section **[Releases](URL_DE_VOS_RELEASES)** de ce dépôt GitHub.

1.  Téléchargez l'archive pour votre système d'exploitation.
2.  Décompressez l'archive.
3.  Lancez l'exécutable `sOCRate`.
4.  Cliquez sur `➕` pour ajouter une règle, sélectionnez un dossier à surveiller, et personnalisez les options.
5.  Cliquez sur `▶ Démarrer`. C'est tout !

---

## 🏗️ Pour les Développeurs

Ce projet est entièrement géré et compilé via des workflows GitHub Actions.

### Prérequis

*   Python 3.11+
*   Sur macOS : `brew install tesseract tesseract-lang`
*   Sur Windows : Avoir [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) installé.

### Installation locale

1.  Clonez le dépôt :
    ```sh
    git clone https://github.com/Amaury-codes/sOCRate_newui.git
    cd sOCRate_newui
    ```
2.  Créez un environnement virtuel et installez les dépendances :
    ```sh
    python -m venv venv
    source venv/bin/activate  # Sur macOS/Linux
    # venv\Scripts\activate    # Sur Windows
    pip install -r requirements.txt
    ```
3.  Lancez l'application :
    ```sh
    python socrate_app.py
    ```

### Compilation

La compilation est gérée automatiquement par le workflow `.github/workflows/build.yml`. Il produit des artefacts pour Windows (x64) et macOS (Apple Silicon, arm64).

---
*Projet développé par Amaury Poussier.*
