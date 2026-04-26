# Email — Demande accès sandbox Orange Money CI Business API

**À envoyer depuis** : `yablairuben92@gmail.com`
**Destinataire** : `support.developer@orange.ci` (et `business@orange.ci` en CC)
**Objet** : `Demande d'accès Developer Portal — Intégration paiement scolaire (KLASSCI College)`

> **Note** : Orange Money CI a un Developer Portal officiel : https://developer.orange.com/apis/om-webpay
> Idéalement créer un compte là-bas en parallèle de cet email.

---

Bonjour,

Je développe **KLASSCI College**, une plateforme SaaS de gestion scolaire destinée aux collèges et lycées de Côte d'Ivoire. Nous lançons notre service en juillet 2026 avec un premier établissement client à Abidjan.

Notre plateforme permettra aux **parents d'élèves de payer les frais de scolarité depuis leur téléphone**. Orange Money est l'un des deux moyens de paiement principaux de notre cible (avec Wave).

Je sollicite :

1. **Accès Developer Portal** Orange Money CI pour créer une application en mode sandbox
2. **Credentials de test** (Merchant ID, API Key, Secret) pour intégrer l'API Web Payment
3. **Documentation des webhooks** de confirmation de paiement
4. Les **conditions de partenariat** pour passer en production

**Volume estimé** : 300-500 transactions/mois par école, panier moyen 50 000 à 200 000 FCFA. 5 écoles prévues en année 1.

**Stack** : Backend Python / FastAPI (api.college.klassci.com), webhooks signés HMAC, MySQL multi-tenant.

Cas d'usage précis :
- Parent reçoit un lien de paiement par SMS (frais scolarité)
- Cliquer ouvre le formulaire OM Web Payment
- Webhook confirmation → marquer le paiement comme reçu côté école
- Reçu PDF généré automatiquement et envoyé par email au parent

Pourriez-vous m'orienter vers la procédure d'inscription développeur ?
Je suis disponible pour un appel téléphonique ou une visio.

Merci d'avance.

Cordialement,

**James / Patrick Djedje**
Développeur principal — KLASSCI
📧 yablairuben92@gmail.com
🌐 https://klassci.com
📱 +225 XX XX XX XX XX

---

## Liens utiles à explorer en parallèle

- Developer Portal Orange : https://developer.orange.com/apis/om-webpay
- Documentation OM Web Payment : (chercher la dernière version sur le portail)
- Compte test : https://developer.orange.com/myaccount

## Plan B : intégrateur tiers

Si Orange ne répond pas sous 7 jours, considérer ces agrégateurs (qui ont déjà OM intégré) :
- **CinetPay** (Côte d'Ivoire — https://cinetpay.com) : 3-4% de fees mais setup en 24h
- **PayDunya** (Sénégal mais opère en CI — https://paydunya.com)
- **Pawapay** (multi-pays Afrique)

Trade-off : fees plus élevés (3-4% vs 1.5-2% direct OM) mais time-to-market 1 semaine au lieu de 1 mois.
