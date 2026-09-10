"""La mecanique de la reprise de televersement, decoupee.

Le service `app/services/upload_handoff_service.py` reste la porte d'entree :
il porte les quatre gestes de l'operateur et re-expose tout ce qui suit. Ce
paquet tient ce qu'il y a EN DESSOUS — le registre des cibles et la machine
a etats d'une session — parce qu'un seul fichier les portait tous les deux et
depassait les mille deux cents lignes.

La couture n'est pas inventee : le fichier la tracait deja lui-meme, en
commentaire, sans jamais l'avoir coupee.
"""
