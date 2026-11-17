# Identité visuelle : rose de l'image fournie et blanc glassmorphism

## Rose de référence
- **Source** : image fournie le 17/11/2026, PNG de 418 × 851 px, couleur unie (99,996 % des pixels, soit 355 705 sur 355 718).
- **Valeurs stockées dans le fichier** : 187, 39, 87 (#BB2757). Le fichier contient un profil ICC « Display », c'est-à-dire l'espace Display P3 d'un écran Mac. L'aller-retour par l'espace Lab D50 (L 44,3 ; a 70 ; b 14) le confirme : ces valeurs sont des coordonnées P3.
- **Rose exact pour le navigateur** : `color(display-p3 0.7333 0.1529 0.3412)`, utilisé sur les écrans à large gamut, dont les écrans Mac.
- **Équivalent sRGB exact** : **#CC0256**. Il est dans la gamme sRGB et sert de repli pour les autres écrans ainsi que pour les tests de contraste.
- **Pourquoi pas #BB2757** : un code CSS #BB2757 est interprété en sRGB. Il donnerait un rose plus terne que celui de l'image, ce qui était le cas dans la première passe de la refonte, corrigée depuis.

## Thème
- **Fichiers** : `apps/web/src/styles/tokens.css` (tokens), `apps/web/src/styles/components.css` (composants). Aucune autre couleur n'est codée en dur dans l'interface.
- **Thème par défaut** : clair, quel que soit le réglage du système.
  - Fond blanc légèrement rosé (#fdf6f9), halos roses.
  - Verre blanc translucide (62 % et 82 %) avec flou, bordures lumineuses, ombres teintées de rose.
  - Verre rose pour les sélections et certains encarts.
- **Rose principal** : boutons principaux, élément de navigation actif, onglets, étapes, cases, anneau de focus.
- **Couleurs d'état** : vert, ambre, rouge et bleu restent distincts du rose. Elles sont toujours accompagnées d'une icône et d'un texte.
- **Mode sombre** : facultatif, en rose profond, sans bleu nuit, violet ni noir. Il ne s'applique que sur choix explicite.
- **Vérifications** :
  - contrastes WCAG AA du texte et des états, en clair et en sombre (`tokens.test.ts`) ;
  - test e2e de l'élément actif et du fond clair sous un système en mode sombre ;
  - captures de tous les écrans, sur ordinateur et sur mobile.
