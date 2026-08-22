import { describe, it, expect } from 'vitest';
import { getMcpManifest } from '../../src/utils/mcp';

describe('WebMCP Manifest', () => {
	it('generates a complete manifest with tools, prompts, and resources', () => {
		const manifest = getMcpManifest('de');
		expect(manifest.version).toBe('1.0.0');
		expect(manifest.tools.length).toBe(3);
		expect(manifest.prompts.length).toBe(3);
		expect(manifest.resources.length).toBe(4);
	});

	describe('Tools', () => {
		it('executes get_rhine_temperature tool in German and English', async () => {
			const manifest = getMcpManifest('de');
			const tempTool = manifest.tools.find((tool) => tool.name === 'get_rhine_temperature');
			expect(tempTool).toBeDefined();

			const responseDe = await tempTool!.execute({ lang: 'de' });
			expect(responseDe.content[0].type).toBe('text');
			const dataDe = JSON.parse(responseDe.content[0].text);
			expect(dataDe.waterTemperature.unit).toBe('°C');
			expect(dataDe.waterTemperature.value).toBeGreaterThan(0);
			expect(dataDe.language).toBe('de');
			expect(dataDe.location).toBe('Basel, Switzerland');

			const responseEn = await tempTool!.execute({ lang: 'en' });
			const dataEn = JSON.parse(responseEn.content[0].text);
			expect(dataEn.language).toBe('en');
		});

		it('executes get_swimming_prognosis tool', async () => {
			const manifest = getMcpManifest('de');
			const prognosisTool = manifest.tools.find((tool) => tool.name === 'get_swimming_prognosis');
			expect(prognosisTool).toBeDefined();

			const response = await prognosisTool!.execute();
			const data = JSON.parse(response.content[0].text);
			expect(data.prognosis).toBeDefined();
			expect(data.indices.waterQuality).toBeDefined();
			expect(data.indices.swimmerSafety).toBeDefined();
			expect(data.currentConditions.waterTemperature).toMatch(/°C/);
		});

		it('executes get_rhine_history tool for different metrics and periods', async () => {
			const manifest = getMcpManifest('de');
			const historyTool = manifest.tools.find((tool) => tool.name === 'get_rhine_history');
			expect(historyTool).toBeDefined();

			const responseWeek = await historyTool!.execute({ metric: 'water', period: 'week' });
			const dataWeek = JSON.parse(responseWeek.content[0].text);
			expect(dataWeek.period).toBe('week');
			expect(Array.isArray(dataWeek.waterTemperature.data)).toBe(true);

			const responseAllMonth = await historyTool!.execute({ metric: 'all', period: 'month' });
			const dataAllMonth = JSON.parse(responseAllMonth.content[0].text);
			expect(dataAllMonth.period).toBe('month');
			expect(dataAllMonth.waterTemperature).toBeDefined();
			expect(dataAllMonth.airTemperature).toBeDefined();
			expect(dataAllMonth.waterLevel).toBeDefined();
			expect(dataAllMonth.qualityFactors).toBeDefined();
		});
	});

	describe('Prompts', () => {
		it('generates swimming_advisor prompt messages', async () => {
			const manifest = getMcpManifest('de');
			const advisorPrompt = manifest.prompts.find((prompt) => prompt.name === 'swimming_advisor');
			expect(advisorPrompt).toBeDefined();

			const resultDe = await advisorPrompt!.getMessages({ experienceLevel: 'beginner', lang: 'de' });
			expect(resultDe.messages.length).toBe(1);
			expect(resultDe.messages[0].content.text).toContain('Anfänger');
			expect(resultDe.messages[0].content.text).toContain('Wickelfisch');

			const resultEn = await advisorPrompt!.getMessages({ experienceLevel: 'experienced', lang: 'en' });
			expect(resultEn.messages[0].content.text).toContain('experienced');
			expect(resultEn.messages[0].content.text).toContain('Wickelfisch');
		});

		it('generates daily_rhine_report and rhine_safety_briefing prompt messages', async () => {
			const manifest = getMcpManifest('de');
			const reportPrompt = manifest.prompts.find((prompt) => prompt.name === 'daily_rhine_report');
			const safetyPrompt = manifest.prompts.find((prompt) => prompt.name === 'rhine_safety_briefing');

			expect(reportPrompt).toBeDefined();
			expect(safetyPrompt).toBeDefined();

			const reportResult = await reportPrompt!.getMessages({ lang: 'de' });
			expect(reportResult.messages[0].content.text).toContain('Rhygfuehl');

			const safetyResult = await safetyPrompt!.getMessages({ lang: 'en' });
			expect(safetyResult.messages[0].content.text).toContain('Cold Shock physiology');
		});
	});

	describe('Resources', () => {
		it('reads rhine://basel/current.json resource', async () => {
			const manifest = getMcpManifest('de');
			const currentResource = manifest.resources.find((resource) => resource.uri === 'rhine://basel/current.json');
			expect(currentResource).toBeDefined();

			const result = await currentResource!.read();
			expect(result.contents[0].mimeType).toBe('application/json');
			const parsed = JSON.parse(result.contents[0].text);
			expect(parsed.water).toBeDefined();
			expect(parsed.air).toBeDefined();
			expect(parsed.level).toBeDefined();
			expect(parsed.quality).toBeDefined();
		});

		it('reads rhine://basel/prognosis-logic.md resource', async () => {
			const manifest = getMcpManifest('de');
			const logicResource = manifest.resources.find((resource) => resource.uri === 'rhine://basel/prognosis-logic.md');
			expect(logicResource).toBeDefined();

			const result = await logicResource!.read();
			expect(result.contents[0].mimeType).toBe('text/markdown');
			expect(result.contents[0].text).toContain('Rhine Swimming Recommendation Logic');
			expect(result.contents[0].text).toContain('Rain Impact Score');
		});

		it('reads rhine://basel/faq.json and rhine://basel/llms.txt', async () => {
			const manifest = getMcpManifest('de');
			const faqResource = manifest.resources.find((resource) => resource.uri === 'rhine://basel/faq.json');
			const llmsResource = manifest.resources.find((resource) => resource.uri === 'rhine://basel/llms.txt');

			expect(faqResource).toBeDefined();
			expect(llmsResource).toBeDefined();

			const faqResult = await faqResource!.read();
			const parsedFaq = JSON.parse(faqResult.contents[0].text);
			expect(parsedFaq.de.length).toBeGreaterThan(0);
			expect(parsedFaq.en.length).toBeGreaterThan(0);

			const llmsResult = await llmsResource!.read();
			expect(llmsResult.contents[0].mimeType).toBe('text/plain');
			expect(llmsResult.contents[0].text).toContain('rhygfuehl.ch');
		});
	});
});
