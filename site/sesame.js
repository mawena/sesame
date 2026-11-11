// Sésame : boutons « Copier » des commandes.
(function () {
  'use strict';
  function selectionner(bouton) {
    var r = document.createRange();
    r.selectNodeContents(document.getElementById(bouton.dataset.cible));
    var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
  }
  document.querySelectorAll('.copier').forEach(function (bouton) {
    bouton.hidden = false;
    bouton.addEventListener('click', function () {
      var texte = document.getElementById(bouton.dataset.cible).textContent;
      var fini = function () {
        bouton.textContent = 'Copié';
        bouton.classList.add('copie');
        setTimeout(function () { bouton.textContent = 'Copier'; bouton.classList.remove('copie'); }, 2000);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(texte).then(fini, function () { selectionner(bouton); });
      } else {
        selectionner(bouton);
      }
    });
  });
})();
