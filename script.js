// Sistema de inventario en JavaScript
// Este archivo contiene toda la lógica necesaria para gestionar la lista de
// materiales cargados desde el PDF base y permitir operaciones de agregar,
// editar, eliminar y filtrar ítems. También se gestionan los responsables.

document.addEventListener('DOMContentLoaded', () => {
  // Nota: eliminamos BASE_DATA de esta versión. Los datos iniciales se
  // cargarán desde un archivo separado (data.txt). Si el archivo no se
  // encuentra o no puede parsearse, se utilizará una conversión de base
  // como respaldo.


  /**
   * Responsables predeterminados. Estos son los nombres que aparecen en la
   * instrucción del usuario y se cargan la primera vez que se abre la
   * aplicación. Posteriormente pueden editarse o añadirse otros.
   */
  const DEFAULT_RESPONSABLES = [
    'Allan Umaña Ortiz',
    'Raúl Barrantes Dominguez',
    'Jorge Luis Espinales Velásquez',
    'Eduardo Rocha Vargas',
    'Carlos Francisco. Solano Soto',
    'Jesús Sibaja Vargas'
  ];

  /**
   * Ruta remota del archivo de datos. Este enlace apunta al contenido
   * "raw" de un archivo en GitHub. La ruta debe ser pública y
   * accesible para que el navegador pueda obtenerla mediante fetch.
   * Si deseas utilizar otro archivo remoto, modifica esta constante con
   * la URL raw correspondiente.
   */
  const REMOTE_DATA_URL =
    'https://raw.githubusercontent.com/aumana01/InventarioTelemetria/8f9d755dfdd44e1007354881ef0b7d9ecc107bed/data.txt';

  // Estado de la aplicación
  let items = [];
  let responsables = [];
  let editingIndex = null;
  let fromQuickAdd = false; // bandera para seleccionar responsable recién agregado

  /**
   * Convierte una cadena con formato de moneda costarricense (₡) en un
   * número de JavaScript. Elimina símbolos, puntos de miles y comas de
   * decimales para obtener el valor numérico.
   * @param {string|number} value Cadena de moneda o número
   * @returns {number}
   */
  function parseCurrency(value) {
    if (typeof value === 'number') return value;
    if (!value) return 0;
    // eliminar cualquier caracter que no sea número, punto o coma
    let numStr = value
      .toString()
      .replace(/[^0-9,\.]/g, '')
      .replace(/\./g, '')
      .replace(/,/g, '.');
    const parsed = parseFloat(numStr);
    return isNaN(parsed) ? 0 : parsed;
  }

  /**
   * Formatea un número a la notación costarricense con símbolo de colón y
   * separadores de miles. Mantiene dos decimales.
   * @param {number} num
   * @returns {string}
   */
  function formatCurrency(num) {
    return '₡' + num.toLocaleString('es-CR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  /**
   * Carga la lista de responsables desde localStorage o inicializa con
   * valores predeterminados si no existen.
   * @returns {string[]} lista de responsables
   */
  function loadResponsables() {
    const stored = localStorage.getItem('responsables');
    if (stored) {
      try {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed)) return parsed;
      } catch (e) {
        console.warn('Error al parsear responsables:', e);
      }
    }
    // Si no hay datos, usar predeterminados y guardarlos
    localStorage.setItem('responsables', JSON.stringify(DEFAULT_RESPONSABLES));
    return [...DEFAULT_RESPONSABLES];
  }

  /**
   * Guarda la lista de responsables actual en localStorage.
   */
  function saveResponsables() {
    localStorage.setItem('responsables', JSON.stringify(responsables));
  }

  /**
   * Convierte una estructura base vacía a la estructura interna del
   * inventario. Este método se conserva únicamente por compatibilidad
   * y devuelve un arreglo vacío. Si se desea proporcionar datos de
   * respaldo cuando no exista el archivo de datos, este método puede
   * modificarse para generar ítems predeterminados.
   * @returns {object[]} lista vacía
   */
  function convertBaseToItems() {
    return [];
  }

  /**
   * Carga la lista de ítems. Primero intenta leer el arreglo guardado en
   * localStorage bajo la clave "items". Si existe, se utiliza dicho
   * contenido para permitir mantener cambios no guardados entre recargas.
   * Si no existe, intenta obtener los datos desde el archivo data.txt
   * ubicado en la raíz de la aplicación. Este archivo debe contener un
   * arreglo JSON con la estructura de ítems. En caso de error al leer
   * o parsear el archivo, se devuelve un arreglo vacío utilizando
   * convertBaseToItems() como respaldo.
   *
   * @returns {Promise<object[]>} Promesa que resuelve con el arreglo de ítems
   */
  async function loadItems() {
    // Siempre intentamos cargar desde el archivo de datos remoto. Si esto
    // falla, intentamos cargar un archivo local (data.txt) dentro de la
    // carpeta de la aplicación. Si ambos fallan se devolverán datos de
    // respaldo vacíos. LocalStorage no se usa para inicializar la lista
    // de ítems para evitar conservar categorías antiguas o datos
    // inconsistentes.
    // 0. intentar cargar datos guardados en localStorage. Esto permite
    // conservar las ediciones realizadas entre recargas sin necesidad de
    // reescribir el archivo remoto. Si existe un arreglo válido en
    // localStorage bajo la clave "items", se utiliza directamente.
    try {
      const stored = localStorage.getItem('items');
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed)) {
          return parsed;
        }
      }
    } catch (e) {
      console.warn('Error al leer ítems desde localStorage:', e);
    }

    // 1. intentar obtener datos desde la ruta remota
    try {
      const remoteRes = await fetch(REMOTE_DATA_URL);
      if (remoteRes.ok) {
        const txt = await remoteRes.text();
        const parsedRemote = JSON.parse(txt);
        if (Array.isArray(parsedRemote)) {
          return parsedRemote;
        }
      } else {
        console.warn('No se pudo cargar archivo remoto:', remoteRes.statusText);
      }
    } catch (e) {
      console.warn('Error al cargar archivo remoto:', e);
    }
    // 2. intentar cargar data.txt local (para cuando se ejecute desde servidor local)
    try {
      const localRes = await fetch('data.txt');
      if (localRes.ok) {
        const text = await localRes.text();
        const parsed = JSON.parse(text);
        if (Array.isArray(parsed)) {
          return parsed;
        }
      } else {
        console.warn('No se pudo cargar data.txt local:', localRes.statusText);
      }
    } catch (e) {
      console.warn('Error al cargar data.txt local:', e);
    }
    // Respaldo: devolver arreglo vacío
    console.warn('Utilizando datos de respaldo vacíos.');
    return convertBaseToItems();
  }

  /**
   * Guarda el arreglo de ítems en localStorage.
   */
  function saveItems() {
    localStorage.setItem('items', JSON.stringify(items));
  }

  /**
   * Rellena el select de responsables en el formulario con la lista
   * actualizada. También intenta mantener la selección actual si existe.
   */
  function populateResponsableSelect() {
    const responsableSelect = document.getElementById('itemResponsable');
    // guardar selección previa
    const previousValue = responsableSelect.value;
    responsableSelect.innerHTML = '';
    responsables.forEach((resp) => {
      const option = document.createElement('option');
      option.value = resp;
      option.textContent = resp;
      responsableSelect.appendChild(option);
    });
    // volver a seleccionar si existía
    if (previousValue && responsables.includes(previousValue)) {
      responsableSelect.value = previousValue;
    } else {
      responsableSelect.selectedIndex = 0;
    }
  }

  /**
   * Actualiza la lista de categorías disponibles tanto para filtros como
   * para sugerencias en el formulario. Extrae categorías de todos los ítems.
   */
  function updateCategoryList() {
    const categories = Array.from(new Set(items.map((it) => it.categoria || ''))).filter((c) => c);
    const categoryFilter = document.getElementById('categoryFilter');
    const categoryList = document.getElementById('categoryList');
    // limpiar
    categoryFilter.innerHTML = '<option value="">Todas</option>';
    categoryList.innerHTML = '';
    categories.forEach((cat) => {
      // añadir al filtro
      const opt = document.createElement('option');
      opt.value = cat;
      opt.textContent = cat;
      categoryFilter.appendChild(opt);
      // añadir al datalist
      const datOpt = document.createElement('option');
      datOpt.value = cat;
      categoryList.appendChild(datOpt);
    });
  }

  /**
   * Ordena los ítems según una columna específica y dirección. Después de
   * ordenar actualiza la tabla. Soporta columnas numéricas, de fecha y
   * de texto. Los campos de costo y cantidad se tratan como números,
   * fechas se parsean con Date y el resto como cadenas para orden
   * lexicográfico.
   *
   * @param {string} column - propiedad del objeto de ítem a ordenar
   * @param {boolean} ascending - true para orden ascendente, false para descendente
   */
  function sortItems(column, ascending = true) {
    items.sort((a, b) => {
      let valA = a[column];
      let valB = b[column];
      // manejar null o undefined
      if (valA === undefined || valA === null) valA = '';
      if (valB === undefined || valB === null) valB = '';
      // convertir a tipo apropiado
      // fechas
      if (column === 'fechaIngreso' || column === 'fechaModificacion') {
        valA = new Date(valA);
        valB = new Date(valB);
      } else if (typeof valA === 'number' && typeof valB === 'number') {
        // números ya están como number
      } else if (!isNaN(parseFloat(valA)) && !isNaN(parseFloat(valB))) {
        // tratar cadenas numéricas
        valA = parseFloat(valA);
        valB = parseFloat(valB);
      } else {
        // convertir a cadena para comparaciones
        valA = valA.toString().toLowerCase();
        valB = valB.toString().toLowerCase();
      }
      if (valA < valB) return ascending ? -1 : 1;
      if (valA > valB) return ascending ? 1 : -1;
      return 0;
    });
    updateTable();
  }

  /**
   * Aplica los filtros seleccionados a la lista de ítems. Retorna true si el
   * ítem debe mostrarse.
   * @param {object} item
   */
  function passesFilters(item) {
    const categoryFilter = document.getElementById('categoryFilter').value;
    const fiDesde = document.getElementById('fechaIngresoDesde').value;
    const fiHasta = document.getElementById('fechaIngresoHasta').value;
    const fmDesde = document.getElementById('fechaModDesde').value;
    const fmHasta = document.getElementById('fechaModHasta').value;
    // Categoría
    if (categoryFilter && item.categoria !== categoryFilter) return false;
    // Fecha de ingreso
    if (fiDesde && new Date(item.fechaIngreso) < new Date(fiDesde)) return false;
    if (fiHasta && new Date(item.fechaIngreso) > new Date(fiHasta)) return false;
    // Fecha de modificación
    if (fmDesde && new Date(item.fechaModificacion) < new Date(fmDesde)) return false;
    if (fmHasta && new Date(item.fechaModificacion) > new Date(fmHasta)) return false;
    return true;
  }

  /**
   * Renderiza la tabla de inventario según el estado actual y filtros
   * aplicados.
   */
  function updateTable() {
    const tbody = document.querySelector('#inventoryTable tbody');
    tbody.innerHTML = '';
    items.forEach((item, index) => {
      if (!passesFilters(item)) return;
      const tr = document.createElement('tr');
      // ID
      const idTd = document.createElement('td');
      idTd.textContent = item.id;
      tr.appendChild(idTd);
      // Categoría
      const catTd = document.createElement('td');
      catTd.textContent = item.categoria;
      tr.appendChild(catTd);
      // Material
      const matTd = document.createElement('td');
      matTd.textContent = item.material;
      tr.appendChild(matTd);
      // Cantidad
      const cantTd = document.createElement('td');
      cantTd.textContent = item.cantidad;
      tr.appendChild(cantTd);
      // Costo unitario
      const costUnitTd = document.createElement('td');
      costUnitTd.textContent = formatCurrency(item.costoUnit);
      tr.appendChild(costUnitTd);
      // Costo total
      const costTotTd = document.createElement('td');
      costTotTd.textContent = formatCurrency(item.costoTotal);
      tr.appendChild(costTotTd);
      // Observaciones
      const obsTd = document.createElement('td');
      obsTd.textContent = item.observaciones;
      tr.appendChild(obsTd);
      // Responsable
      const respTd = document.createElement('td');
      respTd.textContent = item.responsable;
      tr.appendChild(respTd);
      // Marca
      const marcaTd = document.createElement('td');
      marcaTd.textContent = item.marca;
      tr.appendChild(marcaTd);
      // Modelo
      const modeloTd = document.createElement('td');
      modeloTd.textContent = item.modelo;
      tr.appendChild(modeloTd);
      // Fecha de ingreso
      const fiTd = document.createElement('td');
      fiTd.textContent = item.fechaIngreso.split('T')[0];
      tr.appendChild(fiTd);
      // Fecha de modificación
      const fmTd = document.createElement('td');
      fmTd.textContent = item.fechaModificacion.split('T')[0];
      tr.appendChild(fmTd);
      // Foto
      const photoTd = document.createElement('td');
      if (item.foto) {
        const img = document.createElement('img');
        img.src = item.foto;
        img.className = 'img-thumbnail';
        img.alt = 'Foto';
        photoTd.appendChild(img);
      } else {
        photoTd.textContent = '';
      }
      tr.appendChild(photoTd);
      // Acciones
      const actionTd = document.createElement('td');
      actionTd.className = 'text-center';
      // Botón aumentar cantidad
      const plusBtn = document.createElement('button');
      plusBtn.className = 'btn btn-sm btn-success action-btn';
      plusBtn.innerHTML = '<i class="bi bi-plus"></i>';
      plusBtn.title = 'Agregar cantidad';
      plusBtn.addEventListener('click', () => {
        const amountStr = prompt('¿Cuántas unidades desea agregar?');
        const amount = parseInt(amountStr);
        if (isNaN(amount) || amount <= 0) return;
        item.cantidad += amount;
        item.costoTotal = item.cantidad * item.costoUnit;
        item.fechaModificacion = new Date().toISOString();
        saveItems();
        updateTable();
      });
      actionTd.appendChild(plusBtn);
      // Botón disminuir cantidad
      const minusBtn = document.createElement('button');
      minusBtn.className = 'btn btn-sm btn-warning action-btn';
      minusBtn.innerHTML = '<i class="bi bi-dash"></i>';
      minusBtn.title = 'Descontar cantidad';
      minusBtn.addEventListener('click', () => {
        const amountStr = prompt('¿Cuántas unidades desea descontar?');
        const amount = parseInt(amountStr);
        if (isNaN(amount) || amount <= 0) return;
        if (amount > item.cantidad) {
          alert('No puede descontar más de la cantidad existente.');
          return;
        }
        item.cantidad -= amount;
        item.costoTotal = item.cantidad * item.costoUnit;
        item.fechaModificacion = new Date().toISOString();
        saveItems();
        updateTable();
      });
      actionTd.appendChild(minusBtn);
      // Botón editar
      const editBtn = document.createElement('button');
      editBtn.className = 'btn btn-sm btn-info action-btn';
      editBtn.innerHTML = '<i class="bi bi-pencil"></i>';
      editBtn.title = 'Editar ítem';
      editBtn.addEventListener('click', () => {
        openEditItem(index);
      });
      actionTd.appendChild(editBtn);
      // Botón eliminar
      const delBtn = document.createElement('button');
      delBtn.className = 'btn btn-sm btn-danger action-btn';
      delBtn.innerHTML = '<i class="bi bi-trash"></i>';
      delBtn.title = 'Eliminar ítem';
      delBtn.addEventListener('click', () => {
        if (confirm('¿Desea eliminar este ítem?')) {
          items.splice(index, 1);
          saveItems();
          updateCategoryList();
          updateTable();
        }
      });
      actionTd.appendChild(delBtn);
      tr.appendChild(actionTd);
      tbody.appendChild(tr);
    });
  }

  /**
   * Muestra el modal de formulario configurado para un nuevo ítem.
   */
  function openNewItem() {
    editingIndex = null;
    document.getElementById('itemModalLabel').textContent = 'Nuevo ítem';
    // Resetear formulario
    document.getElementById('itemId').value = '';
    document.getElementById('itemCategory').value = '';
    document.getElementById('itemMaterial').value = '';
    document.getElementById('itemQuantity').value = '';
    document.getElementById('itemCostUnit').value = '';
    document.getElementById('itemCostTotal').value = '';
    document.getElementById('itemObservaciones').value = '';
    document.getElementById('itemMarca').value = '';
    document.getElementById('itemModelo').value = '';
    document.getElementById('itemPhoto').value = '';
    const photoPreview = document.getElementById('photoPreview');
    photoPreview.src = '';
    photoPreview.style.display = 'none';
    populateResponsableSelect();
    // Mostrar modal
    const itemModal = new bootstrap.Modal(document.getElementById('itemModal'));
    itemModal.show();
  }

  /**
   * Muestra el modal de formulario cargado con los datos de un ítem existente.
   * @param {number} index Índice del ítem a editar
   */
  function openEditItem(index) {
    editingIndex = index;
    const item = items[index];
    document.getElementById('itemModalLabel').textContent = 'Editar ítem';
    document.getElementById('itemId').value = item.id;
    document.getElementById('itemCategory').value = item.categoria;
    document.getElementById('itemMaterial').value = item.material;
    document.getElementById('itemQuantity').value = item.cantidad;
    document.getElementById('itemCostUnit').value = item.costoUnit;
    document.getElementById('itemCostTotal').value = formatCurrency(item.costoTotal);
    document.getElementById('itemObservaciones').value = item.observaciones;
    document.getElementById('itemMarca').value = item.marca;
    document.getElementById('itemModelo').value = item.modelo;
    populateResponsableSelect();
    document.getElementById('itemResponsable').value = item.responsable;
    const photoPreview = document.getElementById('photoPreview');
    if (item.foto) {
      photoPreview.src = item.foto;
      photoPreview.style.display = 'block';
    } else {
      photoPreview.src = '';
      photoPreview.style.display = 'none';
    }
    // Limpiar input de foto
    document.getElementById('itemPhoto').value = '';
    const itemModal = new bootstrap.Modal(document.getElementById('itemModal'));
    itemModal.show();
  }

  /**
   * Maneja el envío del formulario de ítems para agregar o actualizar un
   * elemento.
   * @param {Event} e Evento de envío
   */
  function handleItemFormSubmit(e) {
    e.preventDefault();
    const idVal = document.getElementById('itemId').value;
    const categoria = document.getElementById('itemCategory').value.trim() || 'General';
    const material = document.getElementById('itemMaterial').value.trim();
    const cantidad = Number(document.getElementById('itemQuantity').value);
    const costoUnit = parseFloat(document.getElementById('itemCostUnit').value);
    const observaciones = document.getElementById('itemObservaciones').value.trim();
    const responsable = document.getElementById('itemResponsable').value;
    const marca = document.getElementById('itemMarca').value.trim();
    const modelo = document.getElementById('itemModelo').value.trim();
    let fotoData = '';
    const photoInput = document.getElementById('itemPhoto');
    const readerPromise = new Promise((resolve) => {
      if (photoInput.files && photoInput.files[0]) {
        const reader = new FileReader();
        reader.onload = function (ev) {
          resolve(ev.target.result);
        };
        reader.readAsDataURL(photoInput.files[0]);
      } else {
        resolve(null);
      }
    });
    readerPromise.then((dataUrl) => {
      fotoData = dataUrl || '';
      const nowIso = new Date().toISOString();
      if (editingIndex === null || editingIndex === undefined) {
        // nuevo ítem
        const newId = items.length ? Math.max(...items.map((it) => it.id)) + 1 : 1;
        const newItem = {
          id: newId,
          categoria,
          material,
          cantidad,
          costoUnit,
          costoTotal: cantidad * costoUnit,
          observaciones,
          responsable,
          marca,
          modelo,
          fechaIngreso: nowIso,
          fechaModificacion: nowIso,
          foto: fotoData
        };
        items.push(newItem);
      } else {
        // editar existente
        const item = items[editingIndex];
        item.categoria = categoria;
        item.material = material;
        item.cantidad = cantidad;
        item.costoUnit = costoUnit;
        item.costoTotal = cantidad * costoUnit;
        item.observaciones = observaciones;
        item.responsable = responsable;
        item.marca = marca;
        item.modelo = modelo;
        item.fechaModificacion = nowIso;
        if (fotoData) {
          // solo actualizar foto si se seleccionó una nueva
          item.foto = fotoData;
        }
      }
      saveItems();
      updateCategoryList();
      updateTable();
      // cerrar modal
      const modalEl = document.getElementById('itemModal');
      bootstrap.Modal.getInstance(modalEl).hide();
    });
  }

  /**
   * Maneja el envío del formulario de nuevo responsable. Añade a la lista
   * global y actualiza el select del formulario de ítems.
   * @param {Event} e
   */
  function handleResponsableSubmit(e) {
    e.preventDefault();
    const nombre = document.getElementById('responsableNombre').value.trim();
    if (!nombre) return;
    if (!responsables.includes(nombre)) {
      responsables.push(nombre);
      saveResponsables();
      populateResponsableSelect();
      // si se creó desde botón rápido, seleccionar este responsable
      if (fromQuickAdd) {
        document.getElementById('itemResponsable').value = nombre;
      }
    }
    // limpiar
    document.getElementById('responsableNombre').value = '';
    fromQuickAdd = false;
    // cerrar modal
    const modalEl = document.getElementById('responsableModal');
    bootstrap.Modal.getInstance(modalEl).hide();
  }

  /**
   * Adjunta todos los listeners necesarios para el funcionamiento del
   * sistema. Se ejecuta una sola vez durante la inicialización.
   */
  function attachEventListeners() {
    // Botón nuevo ítem
    document.getElementById('addItemBtn').addEventListener('click', openNewItem);
    // Botón nuevo responsable
    document.getElementById('addResponsableBtn').addEventListener('click', () => {
      fromQuickAdd = false;
      const modal = new bootstrap.Modal(document.getElementById('responsableModal'));
      modal.show();
    });
    // Botón rápido de responsable dentro del formulario de ítems
    document.getElementById('quickAddResponsable').addEventListener('click', () => {
      fromQuickAdd = true;
      const modal = new bootstrap.Modal(document.getElementById('responsableModal'));
      modal.show();
    });
    // Escuchar cambios en cantidad y costo unitario para actualizar costo total
    document.getElementById('itemQuantity').addEventListener('input', () => {
      updateCostTotalField();
    });
    document.getElementById('itemCostUnit').addEventListener('input', () => {
      updateCostTotalField();
    });
    // Envíos de formularios
    document.getElementById('itemForm').addEventListener('submit', handleItemFormSubmit);
    document.getElementById('responsableForm').addEventListener('submit', handleResponsableSubmit);
    // Filtros
    ['categoryFilter','fechaIngresoDesde','fechaIngresoHasta','fechaModDesde','fechaModHasta'].forEach((id) => {
      document.getElementById(id).addEventListener('change', updateTable);
    });
    // Botón imprimir
    document.getElementById('printBtn').addEventListener('click', () => {
      window.print();
    });

    // Botón guardar base de datos
    document.getElementById('saveDataBtn').addEventListener('click', () => {
      saveDataFile();
    });

    // Botón configurar ruta de datos: abre selector de archivos
    document.getElementById('configPathBtn').addEventListener('click', () => {
      const fileInput = document.getElementById('dataFileInput');
      if (fileInput) fileInput.click();
    });

    // Manejar selección del archivo de datos
    const fileInput = document.getElementById('dataFileInput');
    if (fileInput) {
      fileInput.addEventListener('change', handleDataFileSelected);
    }

    // Listeners para ordenar columnas
    document.querySelectorAll('.sort-asc').forEach((btn) => {
      btn.addEventListener('click', () => {
        const col = btn.getAttribute('data-col');
        sortItems(col, true);
      });
    });
    document.querySelectorAll('.sort-desc').forEach((btn) => {
      btn.addEventListener('click', () => {
        const col = btn.getAttribute('data-col');
        sortItems(col, false);
      });
    });
  }

  /**
   * Calcula y actualiza el campo de costo total en el formulario de ítem
   * cuando se modifican cantidad o costo unitario.
   */
  function updateCostTotalField() {
    const qty = Number(document.getElementById('itemQuantity').value);
    const cost = parseFloat(document.getElementById('itemCostUnit').value);
    if (!isNaN(qty) && !isNaN(cost)) {
      const total = qty * cost;
      document.getElementById('itemCostTotal').value = formatCurrency(total);
    } else {
      document.getElementById('itemCostTotal').value = '';
    }
  }

  /**
   * Maneja la selección de un archivo por parte del usuario para
   * establecer una nueva base de datos. Lee el contenido del archivo
   * seleccionado, lo parsea como JSON y reemplaza el arreglo de ítems
   * actual. Si el contenido no tiene el formato esperado, se muestra
   * un mensaje de error. Tras cargar, actualiza categorías, tabla y
   * almacena temporalmente los datos en localStorage.
   *
   * @param {Event} event
   */
  function handleDataFileSelected(event) {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = function (e) {
      try {
        const text = e.target.result;
        const parsed = JSON.parse(text);
        if (Array.isArray(parsed)) {
          items = parsed;
          // Guardar en localStorage para persistir mientras se encuentre la sesión
          saveItems();
          updateCategoryList();
          updateTable();
          alert('Archivo de datos cargado correctamente.');
        } else {
          alert('El archivo no contiene un arreglo JSON válido.');
        }
      } catch (error) {
        console.error('Error al leer archivo de datos:', error);
        alert('No se pudo cargar el archivo seleccionado. Asegúrese de que sea un archivo JSON válido.');
      } finally {
        // limpiar selección para permitir volver a cargar el mismo archivo si fuera necesario
        event.target.value = '';
      }
    };
    reader.readAsText(file);
  }

  /**
   * Genera un archivo con la representación actual del inventario y
   * dispara su descarga. El contenido se serializa en formato JSON y se
   * almacena dentro de un Blob con tipo text/plain. Al finalizar se
   * actualiza localStorage para que las ediciones persistan en la sesión.
   */
  function saveDataFile() {
    try {
      const jsonString = JSON.stringify(items, null, 2);
      const blob = new Blob([jsonString], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      // nombre de archivo: data.txt para reemplazar el original
      link.download = 'data.txt';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      // guardar también en localStorage para persistir entre recargas
      saveItems();
      alert('La base de datos ha sido exportada exitosamente.');
    } catch (error) {
      console.error('No se pudo guardar la base de datos:', error);
      alert('Error al guardar la base de datos. Consulte la consola para más detalles.');
    }
  }

  // Inicializar la aplicación de forma asíncrona para poder cargar los
  // ítems desde el archivo externo antes de renderizar.
  async function init() {
    responsables = loadResponsables();
    items = await loadItems();
    populateResponsableSelect();
    updateCategoryList();
    updateTable();
    attachEventListeners();
  }
  init();
});