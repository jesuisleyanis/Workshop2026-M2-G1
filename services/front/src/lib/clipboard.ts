/**
 * Copie dans le presse-papiers. `navigator.clipboard` n'existe qu'en contexte sécurisé (HTTPS / localhost) :
 * repli sur execCommand pour une démo servie en HTTP sur IP LAN. Renvoie false si la copie a échoué.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    /* refus (permissions) : on tente le repli */
  }
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    area.remove()
  }
}
