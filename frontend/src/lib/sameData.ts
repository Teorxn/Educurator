/**
 * ¿La respuesta trae lo mismo que ya está en pantalla?
 *
 * Las vistas que se refrescan solas (documentos cada 5 s, panel cada 15 s)
 * llamaban a `setState` en cada vuelta aunque el servidor devolviera
 * exactamente lo mismo. Cada una de esas llamadas vuelve a renderizar la tabla
 * entera y reinicia las transiciones de sus hijos, que es justo lo que se ve
 * como parpadeo periódico. Comparando antes, un sondeo sin novedades no
 * produce ningún render.
 *
 * Comparar serializando es suficiente aquí: son listas y objetos planos que
 * vienen del backend, con las claves en orden estable.
 */
export function sameData(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (a == null || b == null) return false;
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * Envuelve un `setState` para que sólo actualice si el valor cambió.
 * Devuelve el valor anterior intacto cuando no hay novedades, de modo que las
 * referencias se mantienen y React puede saltarse el render.
 */
export function keepIfSame<T>(prev: T, next: T): T {
  return sameData(prev, next) ? prev : next;
}
