# Email — Demande accès sandbox Wave Pay

**À envoyer depuis** : `yablairuben92@gmail.com` (ou alias business si dispo)
**Destinataire** : `partners@wave.com` (et CC `support@wave.com` si tu connais un contact)
**Objet** : `Demande d'accès sandbox API — Intégration paiement scolaire (KLASSCI College, Côte d'Ivoire)`

---

Bonjour,

Je développe **KLASSCI College**, une plateforme SaaS de gestion scolaire destinée aux collèges et lycées de Côte d'Ivoire (https://klassci.com). Nous lançons notre service au mois de juillet 2026 avec un premier établissement client à Abidjan.

Une fonctionnalité clé pour nos écoles est de permettre aux **parents d'élèves de payer les frais de scolarité directement depuis leur téléphone**, et Wave est le moyen de paiement le plus utilisé par notre cible (parents en Côte d'Ivoire et au Sénégal).

J'aimerais intégrer **Wave Business API** dans notre plateforme. Plus précisément, je suis intéressé par :

- **Création de paiements** (parent → école)
- **Webhooks de confirmation** pour mettre à jour automatiquement le statut "payé" côté école
- **Reçus de transaction** pour le suivi côté parent et école

Pour cela, je sollicite :

1. L'**accès aux credentials sandbox** pour pouvoir développer et tester l'intégration sans frais
2. La **documentation technique de l'API** (endpoints, format webhooks, signature de sécurité)
3. Les **conditions de partenariat** pour passer en production une fois l'intégration validée

Notre estimation de volume au lancement : **300-500 transactions / mois** par école, avec un panier moyen de **50 000 à 200 000 FCFA**. Nous prévoyons d'onboarder 5 écoles en année 1.

Stack technique côté KLASSCI :
- Backend Python / FastAPI (api.college.klassci.com)
- Webhooks signés via HMAC
- Base de données MySQL multi-tenant

Pourriez-vous m'orienter vers la procédure d'inscription développeur ? Je suis disponible pour un appel ou une visio si nécessaire.

Merci d'avance pour votre retour.

Cordialement,

**James / Patrick Djedje**
Développeur principal — KLASSCI
📧 yablairuben92@gmail.com
🌐 https://klassci.com
📱 +225 XX XX XX XX XX (à compléter)

---

## Pourquoi Wave en premier ?

- **Adoption massive en Afrique de l'Ouest** (CI + Sénégal + Mali)
- **Frais de transaction bas** (1% pour les paiements business, vs 2-3% Orange Money)
- **API moderne** (Webhooks, REST, documentation publique)
- **Pas de minimum mensuel** (vs Stripe qui n'opère pas en CI)

Si Wave répond, on intégre Wave en S7. Si pas de réponse en 1 semaine, on bascule sur Orange Money en parallèle.
