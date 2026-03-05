"""
Compatibilité Python 3.13 pour Streamlit Cloud.

Python 3.13 a supprimé le module standard `imghdr`, mais certaines versions
de Streamlit l'importent encore (`import imghdr`). Ce petit module local
fournit un stub minimal pour éviter l'erreur d'import.

Pour l'usage de cette app, un simple `what()` qui renvoie toujours None
suffit : Streamlit tombera sur d'autres mécanismes (Pillow, etc.) pour
gérer les images, et on évite l'arrêt de l'application.
"""

from typing import BinaryIO, Optional, Union


def what(file: Union[str, BinaryIO], h: Optional[bytes] = None) -> Optional[str]:
    """
    Stub compatible avec l'ancienne signature de imghdr.what().
    Renvoie toujours None (type d'image inconnu).
    """
    return None

