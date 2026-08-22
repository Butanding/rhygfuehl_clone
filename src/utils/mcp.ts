import waterData from '../../data/data/waterData.json';
import airData from '../../data/data/airData.json';
import levelData from '../../data/data/levelData.json';
import qualityData from '../../data/data/qualityData.json';
import metadata from '../../data/data/metadata.json';
import de from '../locales/de.json';
import en from '../locales/en.json';
import prognosisLogicMarkdown from '../../docs/prognosis-logic.md?raw';

export interface MCPTool {
	name: string;
	description: string;
	inputSchema: {
		type: 'object';
		properties: Record<string, any>;
		required?: string[];
	};
	execute: (args?: Record<string, any>) => Promise<{ content: Array<{ type: 'text'; text: string }> }>;
}

export interface MCPPromptArgument {
	name: string;
	description: string;
	required?: boolean;
}

export interface MCPPromptMessage {
	role: 'user' | 'assistant' | 'system';
	content: {
		type: 'text';
		text: string;
	};
}

export interface MCPPrompt {
	name: string;
	description: string;
	arguments?: MCPPromptArgument[];
	getMessages: (args?: Record<string, any>) => Promise<{
		description?: string;
		messages: MCPPromptMessage[];
	}>;
}

export interface MCPResourceContent {
	uri: string;
	mimeType: string;
	text: string;
}

export interface MCPResource {
	uri: string;
	name: string;
	description: string;
	mimeType: string;
	read: () => Promise<{ contents: MCPResourceContent[] }>;
}

export interface WebMCPManifest {
	version: string;
	tools: MCPTool[];
	prompts: MCPPrompt[];
	resources: MCPResource[];
}

function resolveLocale(lang?: string, defaultLang: 'de' | 'en' = 'de') {
	if (lang === 'en' || (lang === undefined && defaultLang === 'en')) {
		return { locale: 'en' as const, strings: en };
	}
	return { locale: 'de' as const, strings: de };
}

function getPrognosisLabel(score: number, strings: typeof de | typeof en): string {
	if (score === 3) return strings.prognosisExcellent;
	if (score === 2) return strings.prognosisGood;
	return strings.prognosisDiscouraged;
}

function getQualityLabel(score: number, strings: typeof de | typeof en): string {
	if (score === 3) return strings.qualityExcellent;
	if (score === 2) return strings.qualityGood;
	return strings.qualityDiscouraged;
}

function getSafetyLabel(score: number, strings: typeof de | typeof en): string {
	if (score === 3) return strings.safetySafe;
	if (score === 2) return strings.safetyCaution;
	return strings.safetyDiscouraged;
}

export function getMcpManifest(defaultLang: 'de' | 'en' = 'de'): WebMCPManifest {
	const currentWaterTemp = waterData.actualValue.toFixed(1);
	const currentAirTemp = airData.actualValue.toFixed(1);
	const currentWaterLevel = levelData.actualValue > 0
		? `+${levelData.actualValue.toFixed(2)}`
		: levelData.actualValue.toFixed(2);

	const defaultStrings = defaultLang === 'en' ? en : de;

	const tools: MCPTool[] = [
		{
			name: 'get_rhine_temperature',
			description: defaultStrings.mcp.tools.tempDesc,
			inputSchema: {
				type: 'object',
				properties: {
					lang: {
						type: 'string',
						enum: ['de', 'en'],
						description: defaultStrings.mcp.tools.paramLang
					}
				}
			},
			execute: async (args) => {
				const { locale, strings } = resolveLocale(args?.lang, defaultLang);
				const formattedResult = {
					waterTemperature: {
						value: Number(currentWaterTemp),
						unit: '°C',
						formatted: `${currentWaterTemp} °C`,
						description: strings.waterTempDesc,
						station: strings.sourceWeil
					},
					airTemperature: {
						value: Number(currentAirTemp),
						unit: '°C',
						formatted: `${currentAirTemp} °C`,
						description: strings.airTempDesc,
						station: strings.sourcePromenade
					},
					waterLevel: {
						value: Number(levelData.actualValue.toFixed(2)),
						unit: 'm',
						formatted: `${currentWaterLevel} m`,
						description: strings.waterLevelDesc,
						station: strings.sourceKleinbasel
					},
					lastUpdate: waterData.lastUpdate,
					location: 'Basel, Switzerland',
					language: locale
				};

				return {
					content: [
						{
							type: 'text',
							text: JSON.stringify(formattedResult, null, 2)
						}
					]
				};
			}
		},
		{
			name: 'get_swimming_prognosis',
			description: defaultStrings.mcp.tools.prognosisDesc,
			inputSchema: {
				type: 'object',
				properties: {
					lang: {
						type: 'string',
						enum: ['de', 'en'],
						description: defaultStrings.mcp.tools.paramLang
					}
				}
			},
			execute: async (args) => {
				const { locale, strings } = resolveLocale(args?.lang, defaultLang);

				const result = {
					prognosis: {
						score: qualityData.quality,
						label: getPrognosisLabel(qualityData.quality, strings),
						disclaimer: strings.prognosisDisclaimer
					},
					indices: {
						waterQuality: {
							score: qualityData.indices?.quality,
							label: getQualityLabel(qualityData.indices?.quality, strings),
							description: strings.mcp.indices.qualityExplanation
						},
						swimmerSafety: {
							score: qualityData.indices?.safety,
							label: getSafetyLabel(qualityData.indices?.safety, strings),
							description: strings.mcp.indices.safetyExplanation
						}
					},
					currentConditions: {
						waterTemperature: `${currentWaterTemp} °C`,
						airTemperature: `${currentAirTemp} °C`,
						waterLevel: `${currentWaterLevel} m`
					},
					lastUpdate: qualityData.lastUpdate,
					sourceCodebergDocs: 'https://codeberg.org/chric/rhygfuehl/src/branch/main/docs/prognosis-logic.md',
					language: locale
				};

				return {
					content: [
						{
							type: 'text',
							text: JSON.stringify(result, null, 2)
						}
					]
				};
			}
		},
		{
			name: 'get_rhine_history',
			description: defaultStrings.mcp.tools.historyDesc,
			inputSchema: {
				type: 'object',
				properties: {
					metric: {
						type: 'string',
						enum: ['water', 'air', 'level', 'quality', 'all'],
						description: defaultStrings.mcp.tools.paramMetric
					},
					period: {
						type: 'string',
						enum: ['week', 'month'],
						description: defaultStrings.mcp.tools.paramPeriod
					}
				},
				required: ['metric']
			},
			execute: async (args) => {
				const requestedPeriod = args?.period === 'month' ? 'month' : 'week';
				const requestedMetric = args?.metric || 'all';

				const historyOutput: Record<string, any> = {
					period: requestedPeriod
				};

				if (requestedMetric === 'water' || requestedMetric === 'all') {
					historyOutput.waterTemperature = {
						unit: '°C',
						data: waterData.chart[requestedPeriod]
					};
				}
				if (requestedMetric === 'air' || requestedMetric === 'all') {
					historyOutput.airTemperature = {
						unit: '°C',
						data: airData.chart[requestedPeriod]
					};
				}
				if (requestedMetric === 'level' || requestedMetric === 'all') {
					historyOutput.waterLevel = {
						unit: 'm',
						data: levelData.chart[requestedPeriod]
					};
				}
				if (requestedMetric === 'quality' || requestedMetric === 'all') {
					const radiationEntry = qualityData.data?.find((d: any) => d.measure === 'globalRadiation');
					const rainEntry = qualityData.data?.find((d: any) => d.measure === 'rain');

					historyOutput.qualityFactors = {
						globalRadiation: radiationEntry ? radiationEntry.chart[requestedPeriod] : [],
						rainMm: rainEntry ? rainEntry.chart[requestedPeriod] : []
					};
				}

				return {
					content: [
						{
							type: 'text',
							text: JSON.stringify(historyOutput, null, 2)
						}
					]
				};
			}
		}
	];

	const prompts: MCPPrompt[] = [
		{
			name: defaultStrings.mcp.prompts.advisor.name,
			description: defaultStrings.mcp.prompts.advisor.description,
			arguments: [
				{
					name: 'experienceLevel',
					description: defaultStrings.mcp.prompts.advisor.paramExperience,
					required: false
				},
				{
					name: 'lang',
					description: defaultStrings.mcp.prompts.advisor.paramLang,
					required: false
				}
			],
			getMessages: async (args) => {
				const { strings } = resolveLocale(args?.lang, defaultLang);
				const isBeginner = args?.experienceLevel === 'beginner';
				const experienceLabel = isBeginner
					? (strings === de ? 'Anfänger' : 'beginner')
					: (strings === de ? 'Geübt' : 'experienced');

				const promptText = strings.mcp.prompts.advisor.template
					.replace(/%waterTemp%/g, currentWaterTemp)
					.replace(/%airTemp%/g, currentAirTemp)
					.replace(/%waterLevel%/g, currentWaterLevel)
					.replace(/%prognosisScore%/g, String(qualityData.quality))
					.replace(/%prognosisLabel%/g, getPrognosisLabel(qualityData.quality, strings))
					.replace(/%qualityScore%/g, String(qualityData.indices?.quality ?? ''))
					.replace(/%qualityLabel%/g, getQualityLabel(qualityData.indices?.quality, strings))
					.replace(/%safetyScore%/g, String(qualityData.indices?.safety ?? ''))
					.replace(/%safetyLabel%/g, getSafetyLabel(qualityData.indices?.safety, strings))
					.replace(/%experienceLabel%/g, experienceLabel);

				return {
					description: strings.mcp.prompts.advisor.title,
					messages: [
						{
							role: 'user',
							content: {
								type: 'text',
								text: promptText
							}
						}
					]
				};
			}
		},
		{
			name: defaultStrings.mcp.prompts.report.name,
			description: defaultStrings.mcp.prompts.report.description,
			arguments: [
				{
					name: 'lang',
					description: defaultStrings.mcp.prompts.report.paramLang,
					required: false
				}
			],
			getMessages: async (args) => {
				const { strings } = resolveLocale(args?.lang, defaultLang);
				const promptText = strings.mcp.prompts.report.template
					.replace(/%waterTemp%/g, currentWaterTemp)
					.replace(/%airTemp%/g, currentAirTemp)
					.replace(/%waterLevel%/g, currentWaterLevel)
					.replace(/%lastUpdate%/g, waterData.lastUpdate);

				return {
					description: strings.mcp.prompts.report.title,
					messages: [
						{
							role: 'user',
							content: {
								type: 'text',
								text: promptText
							}
						}
					]
				};
			}
		},
		{
			name: defaultStrings.mcp.prompts.safety.name,
			description: defaultStrings.mcp.prompts.safety.description,
			arguments: [
				{
					name: 'lang',
					description: defaultStrings.mcp.prompts.safety.paramLang,
					required: false
				}
			],
			getMessages: async (args) => {
				const { strings } = resolveLocale(args?.lang, defaultLang);
				const promptText = strings.mcp.prompts.safety.template
					.replace(/%waterTemp%/g, currentWaterTemp)
					.replace(/%waterLevel%/g, currentWaterLevel);

				return {
					description: strings.mcp.prompts.safety.title,
					messages: [
						{
							role: 'user',
							content: {
								type: 'text',
								text: promptText
							}
						}
					]
				};
			}
		}
	];

	const resources: MCPResource[] = [
		{
			uri: 'rhine://basel/current.json',
			name: defaultStrings.mcp.resources.currentName,
			description: defaultStrings.mcp.resources.currentDesc,
			mimeType: 'application/json',
			read: async () => ({
				contents: [
					{
						uri: 'rhine://basel/current.json',
						mimeType: 'application/json',
						text: JSON.stringify(
							{
								water: waterData,
								air: airData,
								level: levelData,
								quality: qualityData,
								metadata
							},
							null,
							2
						)
					}
				]
			})
		},
		{
			uri: 'rhine://basel/prognosis-logic.md',
			name: defaultStrings.mcp.resources.logicName,
			description: defaultStrings.mcp.resources.logicDesc,
			mimeType: 'text/markdown',
			read: async () => ({
				contents: [
					{
						uri: 'rhine://basel/prognosis-logic.md',
						mimeType: 'text/markdown',
						text: prognosisLogicMarkdown
					}
				]
			})
		},
		{
			uri: 'rhine://basel/faq.json',
			name: defaultStrings.mcp.resources.faqName,
			description: defaultStrings.mcp.resources.faqDesc,
			mimeType: 'application/json',
			read: async () => ({
				contents: [
					{
						uri: 'rhine://basel/faq.json',
						mimeType: 'application/json',
						text: JSON.stringify(
							{
								de: [
									{ question: de.faqQ1, answer: de.faqA1.replace('%waterTemp%', currentWaterTemp) },
									{ question: de.faqQ2, answer: de.faqA2.replace('%airTemp%', currentAirTemp) },
									{ question: de.faqQ3, answer: de.faqA3 },
									{ question: de.faqQ4, answer: de.faqA4 },
									{ question: de.faqQ5, answer: de.faqA5 },
									{ question: de.faqQ6, answer: de.faqA6 }
								],
								en: [
									{ question: en.faqQ1, answer: en.faqA1.replace('%waterTemp%', currentWaterTemp) },
									{ question: en.faqQ2, answer: en.faqA2.replace('%airTemp%', currentAirTemp) },
									{ question: en.faqQ3, answer: en.faqA3 },
									{ question: en.faqQ4, answer: en.faqA4 },
									{ question: en.faqQ5, answer: en.faqA5 },
									{ question: en.faqQ6, answer: en.faqA6 }
								]
							},
							null,
							2
						)
					}
				]
			})
		},
		{
			uri: 'rhine://basel/llms.txt',
			name: defaultStrings.mcp.resources.llmsName,
			description: defaultStrings.mcp.resources.llmsDesc,
			mimeType: 'text/plain',
			read: async () => ({
				contents: [
					{
						uri: 'rhine://basel/llms.txt',
						mimeType: 'text/plain',
						text: `# rhygfuehl.ch\n\nLive Rhine data in Basel:\n- Water temperature: ${currentWaterTemp} °C\n- Air temperature: ${currentAirTemp} °C\n- Water level: ${currentWaterLevel} m\n- Last Update: ${waterData.lastUpdate}\n- Source: data.bs.ch`
					}
				]
			})
		}
	];

	return {
		version: '1.0.0',
		tools,
		prompts,
		resources
	};
}
