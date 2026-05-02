const en = {
    'crop-health': { title: 'Crop Health', loading: 'Loading...', error: 'Error', noAssessments: 'No crop health assessments yet', noAssessmentsHint: 'Connect sensors to start monitoring crop stress', waterBalance: 'Water Balance', defaultParams: 'Default params', thermal: 'Thermal', vigor: 'Vigor', diseaseRisk: 'Disease Risk', severity: { LOW: 'Healthy', MEDIUM: 'Monitor', HIGH: 'Stressed', CRITICAL: 'Critical' }, action: { noAction: 'No action needed', monitor: 'Monitor closely', irrigateScheduled: 'Schedule irrigation', irrigateImmediate: 'IRRIGATE NOW' } },
};

const es = {
    'crop-health': { title: 'Salud del Cultivo', loading: 'Cargando...', error: 'Error', noAssessments: 'Sin evaluaciones de salud del cultivo', noAssessmentsHint: 'Conecta sensores para monitorizar el estrés del cultivo', waterBalance: 'Balance Hídrico', defaultParams: 'Parámetros genéricos', thermal: 'Térmico', vigor: 'Vigor', diseaseRisk: 'Riesgo Fitosanitario', severity: { LOW: 'Saludable', MEDIUM: 'Vigilar', HIGH: 'Estresado', CRITICAL: 'Crítico' }, action: { noAction: 'Sin acción necesaria', monitor: 'Monitorizar', irrigateScheduled: 'Programar riego', irrigateImmediate: 'REGAR AHORA' } },
};

const ca = {
    'crop-health': { title: 'Salut del Cultiu', loading: 'Carregant...', error: 'Error', noAssessments: 'Sense avaluacions de salut del cultiu', noAssessmentsHint: 'Connecta sensors per monitoritzar l\'estrès del cultiu', waterBalance: 'Balanç Hídric', defaultParams: 'Paràmetres genèrics', thermal: 'Tèrmic', vigor: 'Vigor', diseaseRisk: 'Risc Fitosanitari', severity: { LOW: 'Saludable', MEDIUM: 'Vigilar', HIGH: 'Estressat', CRITICAL: 'Crític' }, action: { noAction: 'Sense acció', monitor: 'Monitoritzar', irrigateScheduled: 'Programar reg', irrigateImmediate: 'REGAR ARA' } },
};

const eu = {
    'crop-health': { title: 'Laborantzaren Osasuna', loading: 'Kargatzen...', error: 'Errorea', noAssessments: 'Ez dago laborantzaren osasun ebaluaziorik', noAssessmentsHint: 'Konektatu sentsoreak laborantzaren estresa monitorizatzeko', waterBalance: 'Ur Balantzea', defaultParams: 'Parametro generikoak', thermal: 'Termikoa', vigor: 'Indarra', diseaseRisk: 'Arrisku Fitosanitarioa', severity: { LOW: 'Osasuntsu', MEDIUM: 'Zaindu', HIGH: 'Estresatua', CRITICAL: 'Kritikoa' }, action: { noAction: 'Ez da ekintzarik behar', monitor: 'Monitorizatu', irrigateScheduled: 'Ureztatzea programatu', irrigateImmediate: 'UREZTATU ORAIN' } },
};

const fr = {
    'crop-health': { title: 'Santé des Cultures', loading: 'Chargement...', error: 'Erreur', noAssessments: 'Aucune évaluation de santé des cultures', noAssessmentsHint: 'Connectez des capteurs pour surveiller le stress des cultures', waterBalance: 'Bilan Hydrique', defaultParams: 'Paramètres génériques', thermal: 'Thermique', vigor: 'Vigueur', diseaseRisk: 'Risque Phytosanitaire', severity: { LOW: 'Sain', MEDIUM: 'Surveiller', HIGH: 'Stressé', CRITICAL: 'Critique' }, action: { noAction: 'Aucune action', monitor: 'Surveiller', irrigateScheduled: 'Programmer l\'irrigation', irrigateImmediate: 'IRRIGUER MAINTENANT' } },
};

const pt = {
    'crop-health': { title: 'Saúde da Cultura', loading: 'Carregando...', error: 'Erro', noAssessments: 'Sem avaliações de saúde da cultura', noAssessmentsHint: 'Conecte sensores para monitorizar o estresse da cultura', waterBalance: 'Balanço Hídrico', defaultParams: 'Parâmetros genéricos', thermal: 'Térmico', vigor: 'Vigor', diseaseRisk: 'Risco Fitossanitário', severity: { LOW: 'Saudável', MEDIUM: 'Monitorizar', HIGH: 'Estressado', CRITICAL: 'Crítico' }, action: { noAction: 'Nenhuma ação', monitor: 'Monitorizar', irrigateScheduled: 'Programar irrigação', irrigateImmediate: 'IRRIGAR AGORA' } },
};

const nkzSdk = (window as any).__NKZ_SDK__;
if (nkzSdk?.i18n) {
    nkzSdk.i18n.addResources('en', 'crop-health', en['crop-health']);
    nkzSdk.i18n.addResources('es', 'crop-health', es['crop-health']);
    nkzSdk.i18n.addResources('ca', 'crop-health', ca['crop-health']);
    nkzSdk.i18n.addResources('eu', 'crop-health', eu['crop-health']);
    nkzSdk.i18n.addResources('fr', 'crop-health', fr['crop-health']);
    nkzSdk.i18n.addResources('pt', 'crop-health', pt['crop-health']);
}

export { en, es, ca, eu, fr, pt };
